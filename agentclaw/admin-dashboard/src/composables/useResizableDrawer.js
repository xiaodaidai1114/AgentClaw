import { ref, onBeforeUnmount } from 'vue'

/**
 * Composable for making Naive UI drawers resizable by dragging their edge.
 *
 * Usage:
 *   const { drawerWidth, resizeHandleStyle, onResizeMouseDown } = useResizableDrawer({ initial, min, max })
 *   <n-drawer :width="drawerWidth" placement="right">
 *     <div :style="resizeHandleStyle" @mousedown="onResizeMouseDown" />
 *     ...
 *   </n-drawer>
 */
export function useResizableDrawer({ initial = 500, min = 320, max = 1200 } = {}) {
  const drawerWidth = ref(initial)

  let dragging = false
  let startX = 0
  let startWidth = 0

  function onMouseMove(e) {
    if (!dragging) return
    const delta = startX - e.clientX
    drawerWidth.value = Math.min(max, Math.max(min, startWidth + delta))
  }

  function onMouseUp() {
    if (!dragging) return
    dragging = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }

  function onResizeMouseDown(e) {
    e.preventDefault()
    dragging = true
    startX = e.clientX
    startWidth = drawerWidth.value
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }

  onBeforeUnmount(() => {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  })

  const resizeHandleStyle = {
    position: 'absolute',
    left: '0',
    top: '0',
    width: '6px',
    height: '100%',
    cursor: 'col-resize',
    zIndex: '10',
    background: 'transparent',
  }

  return {
    drawerWidth,
    resizeHandleStyle,
    onResizeMouseDown,
  }
}
