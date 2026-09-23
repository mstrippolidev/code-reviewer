function rollupStatus(childStatuses) {
  if (childStatuses.includes('failed')) {
    return 'failed'
  }
  if (childStatuses.some((childStatus) => childStatus === 'pending' || childStatus === 'processing')) {
    return 'pending'
  }
  if (childStatuses.every((childStatus) => childStatus === 'skipped')) {
    return 'skipped'
  }
  return 'indexed'
}

function compareNodes(a, b) {
  if (a.type !== b.type) {
    return a.type === 'folder' ? -1 : 1
  }
  return a.name.localeCompare(b.name)
}

function finalizeFolder(folder) {
  const childStatuses = folder.children.map((child) => (child.type === 'folder' ? finalizeFolder(child) : child.status))
  folder.children.sort(compareNodes)
  folder.status = rollupStatus(childStatuses)
  return folder.status
}

function ensureFolder(root, foldersByPath, segments) {
  let path = ''
  let children = root
  for (const segment of segments) {
    path = path ? `${path}/${segment}` : segment
    let folder = foldersByPath.get(path)
    if (!folder) {
      folder = { name: segment, path, type: 'folder', children: [] }
      foldersByPath.set(path, folder)
      children.push(folder)
    }
    children = folder.children
  }
  return children
}

export function buildFileTree(files) {
  const root = []
  const foldersByPath = new Map()

  for (const file of files) {
    const segments = file.path.split('/')
    const fileName = segments.pop()
    const children = ensureFolder(root, foldersByPath, segments)
    children.push({
      name: fileName,
      path: file.path,
      type: 'file',
      status: file.status,
      statusReason: file.statusReason ?? null,
      indexedAt: file.indexedAt ?? null,
    })
  }

  for (const node of root) {
    if (node.type === 'folder') {
      finalizeFolder(node)
    }
  }
  root.sort(compareNodes)

  return root
}
