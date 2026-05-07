"""
统一的进程/线程/任务生命周期管理器

负责追踪和回收所有后台资源：
- asyncio.Task
- threading.Thread
- multiprocessing.Process
- 其他需要显式清理的资源

确保应用关闭时所有资源被正确释放。
"""

import asyncio
import multiprocessing
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class ResourceType(Enum):
    """资源类型"""
    TASK = "task"
    THREAD = "thread"
    PROCESS = "process"
    CUSTOM = "custom"


class ResourceState(Enum):
    """资源状态"""
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class ResourceInfo:
    """资源信息"""
    id: str
    type: ResourceType
    name: str
    resource: Any
    state: ResourceState = ResourceState.STARTING
    owner: Optional[str] = None  # 所属模块/组件
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    cleanup_callback: Optional[Callable] = None


class ResourceManager:
    """
    全局资源管理器（单例）

    使用示例：
        rm = ResourceManager.get_instance()

        # 注册 task
        task = asyncio.create_task(some_coroutine())
        rm.register_task("my_task", task, owner="my_module")

        # 注册 process
        proc = multiprocessing.Process(target=func)
        proc.start()
        rm.register_process("my_proc", proc, owner="my_module")

        # 关闭时自动清理
        await rm.shutdown()
    """

    _instance: Optional["ResourceManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._resources: Dict[str, ResourceInfo] = {}
        self._resource_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    @classmethod
    def get_instance(cls) -> "ResourceManager":
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置实例（测试用）"""
        cls._instance = None

    async def start(self):
        """启动资源管理器"""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("ResourceManager started")

    async def shutdown(self, timeout: float = 30.0):
        """
        关闭资源管理器，清理所有资源

        Args:
            timeout: 总超时时间（秒）
        """
        if not self._running:
            return

        logger.info(f"ResourceManager shutting down ({len(self._resources)} resources)")
        self._running = False
        self._shutdown_event.set()

        # 停止监控任务
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # 清理所有资源
        start_time = time.time()
        remaining_timeout = timeout

        async with self._resource_lock:
            resources = list(self._resources.values())

        for res in resources:
            if time.time() - start_time >= timeout:
                logger.warning(f"Shutdown timeout reached, {len(self._resources)} resources remaining")
                break

            remaining_timeout = timeout - (time.time() - start_time)
            await self._cleanup_resource(res, timeout=remaining_timeout)

        logger.info("ResourceManager shutdown complete")

    async def register_task(
        self,
        name: str,
        task: asyncio.Task,
        owner: Optional[str] = None,
        cleanup_callback: Optional[Callable] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        注册 asyncio.Task

        Returns:
            resource_id
        """
        resource_id = f"task_{name}_{id(task)}"

        async with self._resource_lock:
            if resource_id in self._resources:
                logger.warning(f"Resource already registered: {resource_id}")
                return resource_id

            self._resources[resource_id] = ResourceInfo(
                id=resource_id,
                type=ResourceType.TASK,
                name=name,
                resource=task,
                state=ResourceState.RUNNING if not task.done() else ResourceState.STOPPED,
                owner=owner,
                cleanup_callback=cleanup_callback,
                metadata=metadata or {},
            )

        logger.debug(f"Registered task: {name} (owner={owner})")
        return resource_id

    async def register_thread(
        self,
        name: str,
        thread: threading.Thread,
        owner: Optional[str] = None,
        cleanup_callback: Optional[Callable] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """注册 threading.Thread"""
        resource_id = f"thread_{name}_{id(thread)}"

        async with self._resource_lock:
            if resource_id in self._resources:
                logger.warning(f"Resource already registered: {resource_id}")
                return resource_id

            self._resources[resource_id] = ResourceInfo(
                id=resource_id,
                type=ResourceType.THREAD,
                name=name,
                resource=thread,
                state=ResourceState.RUNNING if thread.is_alive() else ResourceState.STOPPED,
                owner=owner,
                cleanup_callback=cleanup_callback,
                metadata=metadata or {},
            )

        logger.debug(f"Registered thread: {name} (owner={owner})")
        return resource_id

    async def register_process(
        self,
        name: str,
        process: multiprocessing.Process,
        owner: Optional[str] = None,
        cleanup_callback: Optional[Callable] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """注册 multiprocessing.Process"""
        resource_id = f"process_{name}_{id(process)}"

        async with self._resource_lock:
            if resource_id in self._resources:
                logger.warning(f"Resource already registered: {resource_id}")
                return resource_id

            self._resources[resource_id] = ResourceInfo(
                id=resource_id,
                type=ResourceType.PROCESS,
                name=name,
                resource=process,
                state=ResourceState.RUNNING if process.is_alive() else ResourceState.STOPPED,
                owner=owner,
                cleanup_callback=cleanup_callback,
                metadata=metadata or {},
            )

        logger.debug(f"Registered process: {name} (owner={owner})")
        return resource_id

    async def unregister(self, resource_id: str, cleanup: bool = True) -> bool:
        """
        注销资源

        Args:
            resource_id: 资源ID
            cleanup: 是否执行清理

        Returns:
            是否成功注销
        """
        async with self._resource_lock:
            res = self._resources.get(resource_id)
            if not res:
                return False

            if cleanup:
                await self._cleanup_resource(res)

            del self._resources[resource_id]

        logger.debug(f"Unregistered resource: {resource_id}")
        return True

    async def unregister_by_owner(self, owner: str, cleanup: bool = True):
        """注销某个所有者的所有资源"""
        async with self._resource_lock:
            resources = [r for r in self._resources.values() if r.owner == owner]

        for res in resources:
            await self.unregister(res.id, cleanup=cleanup)

        logger.info(f"Unregistered {len(resources)} resources for owner: {owner}")

    async def get_resource(self, resource_id: str) -> Optional[ResourceInfo]:
        """获取资源信息"""
        async with self._resource_lock:
            return self._resources.get(resource_id)

    async def list_resources(
        self,
        owner: Optional[str] = None,
        resource_type: Optional[ResourceType] = None,
        state: Optional[ResourceState] = None,
    ) -> List[ResourceInfo]:
        """列出资源"""
        async with self._resource_lock:
            resources = list(self._resources.values())

        if owner:
            resources = [r for r in resources if r.owner == owner]
        if resource_type:
            resources = [r for r in resources if r.type == resource_type]
        if state:
            resources = [r for r in resources if r.state == state]

        return resources

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self._resource_lock:
            resources = list(self._resources.values())

        stats = {
            "total": len(resources),
            "by_type": {},
            "by_state": {},
            "by_owner": {},
        }

        for res in resources:
            # 按类型统计
            type_name = res.type.value
            stats["by_type"][type_name] = stats["by_type"].get(type_name, 0) + 1

            # 按状态统计
            state_name = res.state.value
            stats["by_state"][state_name] = stats["by_state"].get(state_name, 0) + 1

            # 按所有者统计
            owner = res.owner or "unknown"
            stats["by_owner"][owner] = stats["by_owner"].get(owner, 0) + 1

        return stats

    async def _monitor_loop(self):
        """监控循环，定期检查资源状态"""
        try:
            while self._running:
                await asyncio.sleep(10)  # 每10秒检查一次
                await self._check_resources()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Monitor loop error: {e}", exc_info=True)

    async def _check_resources(self):
        """检查所有资源状态"""
        async with self._resource_lock:
            resources = list(self._resources.values())

        dead_resources = []

        for res in resources:
            is_alive = await self._is_resource_alive(res)

            if not is_alive and res.state == ResourceState.RUNNING:
                res.state = ResourceState.FAILED
                dead_resources.append(res)
                if res.type == ResourceType.TASK and res.resource.done() and not res.resource.cancelled():
                    exc = res.resource.exception()
                    if exc is not None:
                        logger.warning(
                            f"Resource died unexpectedly: {res.name} ({res.type.value}): {type(exc).__name__}: {exc}"
                        )
                    else:
                        logger.warning(f"Resource finished unexpectedly: {res.name} ({res.type.value})")
                else:
                    logger.warning(f"Resource died unexpectedly: {res.name} ({res.type.value})")

        # 清理死亡资源
        for res in dead_resources:
            await self.unregister(res.id, cleanup=False)

    async def _is_resource_alive(self, res: ResourceInfo) -> bool:
        """检查资源是否存活"""
        try:
            if res.type == ResourceType.TASK:
                return not res.resource.done()
            elif res.type == ResourceType.THREAD:
                return res.resource.is_alive()
            elif res.type == ResourceType.PROCESS:
                return res.resource.is_alive()
            else:
                return True  # CUSTOM 类型由用户管理
        except Exception:
            return False

    async def _cleanup_resource(self, res: ResourceInfo, timeout: float = 10.0):
        """清理单个资源"""
        if res.state == ResourceState.STOPPED:
            return

        res.state = ResourceState.STOPPING
        logger.debug(f"Cleaning up resource: {res.name} ({res.type.value})")

        try:
            # 执行自定义清理回调
            if res.cleanup_callback:
                if asyncio.iscoroutinefunction(res.cleanup_callback):
                    await res.cleanup_callback()
                else:
                    res.cleanup_callback()

            # 根据类型清理
            if res.type == ResourceType.TASK:
                await self._cleanup_task(res.resource, timeout)
            elif res.type == ResourceType.THREAD:
                await self._cleanup_thread(res.resource, timeout)
            elif res.type == ResourceType.PROCESS:
                await self._cleanup_process(res.resource, timeout)

            res.state = ResourceState.STOPPED
            logger.debug(f"Resource cleaned up: {res.name}")

        except Exception as e:
            logger.error(f"Error cleaning up resource {res.name}: {e}", exc_info=True)
            res.state = ResourceState.FAILED

    async def _cleanup_task(self, task: asyncio.Task, timeout: float):
        """清理 asyncio.Task"""
        if task.done():
            return

        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.warning(f"Task cleanup exception: {e}")

    async def _cleanup_thread(self, thread: threading.Thread, timeout: float):
        """清理 threading.Thread"""
        if not thread.is_alive():
            return

        # 线程没有强制停止机制，只能等待
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning(f"Thread {thread.name} did not stop within timeout")

    async def _cleanup_process(self, process: multiprocessing.Process, timeout: float):
        """清理 multiprocessing.Process"""
        if not process.is_alive():
            return

        # 先尝试 terminate
        process.terminate()
        process.join(timeout=timeout / 2)

        # 如果还活着，强制 kill
        if process.is_alive():
            logger.warning(f"Process {process.name} did not terminate, killing")
            process.kill()
            process.join(timeout=timeout / 2)

        if process.is_alive():
            logger.error(f"Process {process.name} could not be killed")


# 全局便捷函数
def get_resource_manager() -> ResourceManager:
    """获取全局资源管理器实例"""
    return ResourceManager.get_instance()
