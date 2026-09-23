import { useEffect, useState } from 'react'
import { isSelectableForReview } from '../utils/buildFileTree'

export function useFileSelection(resetKey, maxFiles) {
  const [selectedFiles, setSelectedFiles] = useState(new Set())

  useEffect(() => {
    setSelectedFiles(new Set())
  }, [resetKey])

  function addPath(path) {
    if (!path.endsWith('.py')) {
      return
    }
    setSelectedFiles((previous) => {
      if (previous.has(path) || previous.size >= maxFiles) {
        return previous
      }
      return new Set(previous).add(path)
    })
  }

  function removePath(path) {
    setSelectedFiles((previous) => {
      const next = new Set(previous)
      next.delete(path)
      return next
    })
  }

  function toggleNode(node) {
    if (!isSelectableForReview(node)) {
      return
    }
    if (selectedFiles.has(node.path)) {
      removePath(node.path)
    } else {
      addPath(node.path)
    }
  }

  return { selectedFiles, toggleNode, addPath, removePath }
}
