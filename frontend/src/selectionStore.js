/** 资产库多选状态：仅 SPA 内存保持，刷新页面即清空。 */
const selectedIds = new Set()

export function getSelectedIds() {
  return [...selectedIds]
}

export function hasSelected(id) {
  return selectedIds.has(id)
}

export function setSelected(id, on) {
  if (on) selectedIds.add(id)
  else selectedIds.delete(id)
}

export function clearSelected() {
  selectedIds.clear()
}

export function removeSelected(id) {
  selectedIds.delete(id)
}

/** 去掉已不存在于当前资产列表中的勾选。 */
export function pruneSelected(aliveIds) {
  const alive = new Set(aliveIds)
  for (const id of [...selectedIds]) {
    if (!alive.has(id)) selectedIds.delete(id)
  }
}
