import { useState } from 'react'
import { isSelectableForReview } from '../utils/buildFileTree'

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

function formatTimestamp(value) {
  if (!value) {
    return '—'
  }
  return new Date(value).toLocaleString()
}

function isPythonFile(node) {
  return node.type === 'file' && node.name.endsWith('.py')
}

function FileInfoModal({ node, onClose }) {
  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <h3 className="modal-title">{node.name}</h3>
        <dl className="file-info-list">
          <dt>Path</dt>
          <dd>{node.path}</dd>
          <dt>Status</dt>
          <dd className="file-info-status">{node.status ?? 'pending'}</dd>
          <dt>Status reason</dt>
          <dd>{node.statusReason ?? '—'}</dd>
          <dt>Indexed at</dt>
          <dd>{formatTimestamp(node.indexedAt)}</dd>
        </dl>
        <div className="modal-actions">
          <button type="button" className="repo-control-button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function FileTreeNode({ node, depth, expandedPaths, onToggle, onNodeClick, onShowInfo, selectedPaths, onToggleSelect }) {
  const isFolder = node.type === 'folder'
  const isExpanded = expandedPaths.has(node.path)

  const isDraggableForReview = selectedPaths && isSelectableForReview(node)

  return (
    <li>
      <div
        className={`file-tree-node file-tree-${node.type} file-tree-status-${node.status ?? 'pending'}`}
        style={{ paddingLeft: `${depth * 1.25}rem` }}
        onClick={() => (isFolder ? onToggle(node.path) : onNodeClick?.(node))}
        draggable={isDraggableForReview}
        onDragStart={(event) => event.dataTransfer.setData('text/plain', node.path)}
      >
        <span className="file-tree-caret">{isFolder ? (isExpanded ? '▾' : '▸') : ''}</span>
        {selectedPaths && isPythonFile(node) ? (
          <input
            type="checkbox"
            className="file-tree-select"
            checked={selectedPaths.has(node.path)}
            disabled={node.status !== 'indexed'}
            title={node.status !== 'indexed' ? 'Only indexed files can be reviewed' : undefined}
            onClick={(event) => event.stopPropagation()}
            onChange={() => onToggleSelect(node)}
          />
        ) : null}
        <span className="file-tree-name">{node.name}</span>
        <span className="file-tree-glyph">{STATUS_GLYPH[node.status] ?? ''}</span>
        {!isFolder ? (
          <button
            type="button"
            className="file-tree-info-button"
            aria-label={`Info for ${node.name}`}
            onClick={(event) => {
              event.stopPropagation()
              onShowInfo(node)
            }}
          >
            ⓘ
          </button>
        ) : null}
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
              onShowInfo={onShowInfo}
              selectedPaths={selectedPaths}
              onToggleSelect={onToggleSelect}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function FileTree({ nodes, onNodeClick, selectedPaths, onToggleSelect }) {
  const [expandedPaths, setExpandedPaths] = useState(() => collectFolderPaths(nodes, new Set()))
  const [infoNode, setInfoNode] = useState(null)

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
    <>
      <ul className="file-tree">
        {nodes.map((node) => (
          <FileTreeNode
            key={node.path}
            node={node}
            depth={0}
            expandedPaths={expandedPaths}
            onToggle={handleToggle}
            onNodeClick={onNodeClick}
            onShowInfo={setInfoNode}
            selectedPaths={selectedPaths}
            onToggleSelect={onToggleSelect}
          />
        ))}
      </ul>
      {infoNode ? <FileInfoModal node={infoNode} onClose={() => setInfoNode(null)} /> : null}
    </>
  )
}
