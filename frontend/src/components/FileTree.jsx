import { useState } from 'react'

const STATUS_GLYPH = {
  pending: '⏳',
  processing: '⏳',
  indexed: '✓',
  skipped: '–',
  failed: '✗',
}

function collectFolderPaths(nodes, paths) {
  for (const node of nodes) {
    if (node.type === 'folder') {
      paths.add(node.path)
      collectFolderPaths(node.children, paths)
    }
  }
  return paths
}

function FileTreeNode({ node, depth, expandedPaths, onToggle, onNodeClick }) {
  const isFolder = node.type === 'folder'
  const isExpanded = expandedPaths.has(node.path)

  return (
    <li>
      <div
        className={`file-tree-node file-tree-${node.type} file-tree-status-${node.status ?? 'pending'}`}
        style={{ paddingLeft: `${depth * 1.25}rem` }}
        onClick={() => (isFolder ? onToggle(node.path) : onNodeClick?.(node))}
      >
        <span className="file-tree-caret">{isFolder ? (isExpanded ? '▾' : '▸') : ''}</span>
        <span className="file-tree-name">{node.name}</span>
        <span className="file-tree-glyph">{STATUS_GLYPH[node.status] ?? ''}</span>
      </div>
      {isFolder && isExpanded ? (
        <ul>
          {node.children.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              expandedPaths={expandedPaths}
              onToggle={onToggle}
              onNodeClick={onNodeClick}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function FileTree({ nodes, onNodeClick }) {
  const [expandedPaths, setExpandedPaths] = useState(() => collectFolderPaths(nodes, new Set()))

  function handleToggle(path) {
    setExpandedPaths((previous) => {
      const next = new Set(previous)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  return (
    <ul className="file-tree">
      {nodes.map((node) => (
        <FileTreeNode
          key={node.path}
          node={node}
          depth={0}
          expandedPaths={expandedPaths}
          onToggle={handleToggle}
          onNodeClick={onNodeClick}
        />
      ))}
    </ul>
  )
}
