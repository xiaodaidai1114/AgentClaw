"""
Skill 管理器
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .parser import SkillParser
from .schema import Skill
from .executor import SkillEnvironment

logger = logging.getLogger(__name__)


class SkillManager:
    """Skill 管理器 - 加载和管理 Skills"""

    def __init__(self, skills_dir: Optional[str] = None, auto_init_env: bool = True):
        """初始化 SkillManager

        Args:
            skills_dir: 技能目录路径，默认 ./skills
            auto_init_env: 是否自动初始化技能环境（安装依赖），默认 True
        """
        self.skills_dir = Path(skills_dir) if skills_dir else Path("./skills")
        self._skills: Dict[str, Skill] = {}
        self._envs: Dict[str, SkillEnvironment] = {}
        self._name_to_dir: Dict[str, str] = {}  # skill name -> directory name 映射
        self._loaded = False
        self._auto_init_env = auto_init_env

    def load_all(self) -> int:
        """加载所有技能

        Returns:
            加载的技能数量
        """
        if self._loaded:
            return len(self._skills)

        if not self.skills_dir.exists():
            logger.debug(f"Skills directory not found: {self.skills_dir}")
            self._loaded = True
            return 0

        count = 0
        skills_with_env = []
        
        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue

            # 跳过目录名含空格的无效 skill（如手动复制产生的 "xxx copy"）
            if " " in item.name:
                logger.debug(f"Skipping skill directory with spaces: {item.name}")
                continue

            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill = SkillParser.parse(item)
                self._skills[skill.name] = skill
                self._name_to_dir[skill.name] = item.name  # 记录 name -> 目录名映射
                count += 1
                logger.info(f"Loaded skill: {skill.name} (dir: {item.name})")

                # 记录需要初始化环境的 skill
                if skill.requirements_file:
                    skills_with_env.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load skill from {item}: {e}")

        self._loaded = True
        logger.info(f"Loaded {count} skills from {self.skills_dir}")
        
        # 自动初始化所有需要环境的 skills
        if self._auto_init_env and skills_with_env:
            logger.info(f"Initializing {len(skills_with_env)} skill environments...")
            for skill in skills_with_env:
                self._init_skill_env(skill)
            logger.info(f"Skill environments initialized")
        
        return count

    def get_skill_dir_name(self, skill_name: str) -> Optional[str]:
        """获取 skill 的目录名

        Args:
            skill_name: skill 名称（从 SKILL.md frontmatter）

        Returns:
            目录名，如果不存在返回 None
        """
        return self._name_to_dir.get(skill_name)

    def _init_skill_env(self, skill: Skill, force: bool = False) -> bool:
        """初始化技能环境
        
        Args:
            skill: Skill 对象
            force: 强制重新初始化
            
        Returns:
            是否成功
        """
        if not force and skill.name in self._envs:
            return True
        
        env = SkillEnvironment(skill.name, skill.requirements_file)
        if env.ensure_initialized(force=force):
            self._envs[skill.name] = env
            logger.info(f"Initialized environment for skill: {skill.name}")
            return True
        else:
            logger.warning(f"Failed to initialize environment for skill: {skill.name}")
            return False
    
    def init_env(self, name: str, force: bool = False) -> bool:
        """手动初始化指定技能的环境
        
        Args:
            name: 技能名称
            force: 强制重新初始化
            
        Returns:
            是否成功
        """
        skill = self.get(name)
        if not skill:
            logger.warning(f"Skill not found: {name}")
            return False
        
        if not skill.requirements_file:
            logger.debug(f"Skill {name} has no requirements.txt")
            return True
        
        return self._init_skill_env(skill, force=force)
    
    def init_all_envs(self) -> int:
        """初始化所有技能环境
        
        Returns:
            成功初始化的数量
        """
        self._ensure_loaded()
        count = 0
        for skill in self._skills.values():
            if skill.requirements_file and self._init_skill_env(skill):
                count += 1
        return count
    
    def get_env(self, name: str) -> Optional[SkillEnvironment]:
        """获取技能环境
        
        Args:
            name: 技能名称
            
        Returns:
            SkillEnvironment 对象，不存在返回 None
        """
        # 如果环境未初始化，尝试初始化
        if name not in self._envs:
            skill = self.get(name)
            if skill and skill.requirements_file:
                self._init_skill_env(skill)
        
        return self._envs.get(name)

    def get(self, name: str) -> Optional[Skill]:
        """获取指定技能

        Args:
            name: 技能名称

        Returns:
            Skill 对象，不存在返回 None
        """
        self._ensure_loaded()
        return self._skills.get(name)

    def get_many(self, names: List[str]) -> List[Skill]:
        """获取多个技能

        Args:
            names: 技能名称列表

        Returns:
            Skill 对象列表（跳过不存在的）
        """
        self._ensure_loaded()
        result = []
        for name in names:
            skill = self._skills.get(name)
            if skill:
                result.append(skill)
            else:
                logger.warning(f"Skill not found: {name}")
        return result

    def list(self) -> List[Skill]:
        """列出所有技能

        Returns:
            所有已加载的 Skill 列表
        """
        self._ensure_loaded()
        return list(self._skills.values())

    def list_names(self) -> List[str]:
        """列出所有技能名称

        Returns:
            技能名称列表
        """
        self._ensure_loaded()
        return list(self._skills.keys())

    def match(self, query: str) -> List[Skill]:
        """按描述匹配技能（用于自动选择）

        Args:
            query: 查询字符串

        Returns:
            匹配的 Skill 列表（按相关度排序）
        """
        self._ensure_loaded()
        query_lower = query.lower()
        matches = []

        for skill in self._skills.values():
            # 简单的关键词匹配
            desc_lower = skill.description.lower()
            name_lower = skill.name.lower()

            score = 0
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5

            # 检查查询词是否在描述中
            for word in query_lower.split():
                if word in desc_lower:
                    score += 1
                if word in name_lower:
                    score += 2

            if score > 0:
                matches.append((score, skill))

        # 按分数降序排序
        matches.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in matches]

    def reload(self, name: Optional[str] = None) -> bool:
        """重新加载技能

        Args:
            name: 指定技能名称，None 表示全部重载

        Returns:
            是否成功
        """
        if name:
            # 重载单个技能
            skill = self._skills.get(name)
            if not skill:
                return False

            try:
                new_skill = SkillParser.parse(skill.path)
                self._skills[name] = new_skill
                logger.info(f"Reloaded skill: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to reload skill {name}: {e}")
                return False
        else:
            # 全部重载
            self._skills.clear()
            self._loaded = False
            self.load_all()
            return True

    def refresh(self) -> int:
        """增量扫描 skills 目录，加载新增的技能（不影响已加载的）

        Returns:
            新增加载的技能数量
        """
        if not self.skills_dir.exists():
            return 0

        new_count = 0
        new_skills_with_env = []

        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue
            if " " in item.name:
                continue

            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue

            # 跳过已加载的
            if item.name in self._skills:
                continue

            try:
                skill = SkillParser.parse(item)
                self._skills[skill.name] = skill
                self._name_to_dir[skill.name] = item.name
                new_count += 1
                logger.info(f"Discovered new skill: {skill.name}")

                if skill.requirements_file:
                    new_skills_with_env.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load new skill from {item}: {e}")

        # 初始化新 skill 的环境
        if self._auto_init_env and new_skills_with_env:
            for skill in new_skills_with_env:
                self._init_skill_env(skill)

        if new_count > 0:
            logger.info(f"Refreshed: {new_count} new skills discovered")

        return new_count

    def _ensure_loaded(self):
        """确保已加载"""
        if not self._loaded:
            self.load_all()

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        self._ensure_loaded()
        return name in self._skills

    def __iter__(self):
        self._ensure_loaded()
        return iter(self._skills.values())
