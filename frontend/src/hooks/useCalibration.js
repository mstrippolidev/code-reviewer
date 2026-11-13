import { useCallback, useEffect, useState } from 'react'
import {
  CalibrationFinishedError,
  UnauthorizedError,
  fetchCalibrationPair,
  fetchCalibrationProgress,
  fetchNextCalibrationPair,
  saveCalibrationLabel,
} from '../api/client'
import { useUnauthorizedHandler } from './useUnauthorizedHandler'

export function useCalibration() {
  const [pair, setPair] = useState(null)
  const [progress, setProgress] = useState({ labeled: 0, total: 0 })
  const [status, setStatus] = useState('loading')
  const [answeredIds, setAnsweredIds] = useState([])
  const handleUnauthorized = useUnauthorizedHandler()

  const handleFailure = useCallback(
    (error) => {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
      } else {
        setStatus('error')
      }
    },
    [handleUnauthorized],
  )

  const loadNext = useCallback(async () => {
    try {
      setPair(await fetchNextCalibrationPair())
      setStatus('ready')
    } catch (error) {
      if (error instanceof CalibrationFinishedError) {
        setPair(null)
        setStatus('done')
      } else {
        handleFailure(error)
      }
    }
  }, [handleFailure])

  useEffect(() => {
    async function load() {
      try {
        setProgress(await fetchCalibrationProgress())
      } catch (error) {
        handleFailure(error)
        return
      }
      await loadNext()
    }
    load()
  }, [loadNext, handleFailure])

  const answer = useCallback(
    async (isDuplicate, note) => {
      try {
        await saveCalibrationLabel(pair.pair_id, isDuplicate, note)
        setAnsweredIds((ids) => (ids.includes(pair.pair_id) ? ids : [...ids, pair.pair_id]))
        setProgress(await fetchCalibrationProgress())
      } catch (error) {
        handleFailure(error)
        return
      }
      await loadNext()
    },
    [pair, loadNext, handleFailure],
  )

  const goBack = useCallback(async () => {
    const previousIds = answeredIds.filter((id) => id !== pair?.pair_id)
    if (previousIds.length === 0) {
      return
    }
    const previousId = previousIds[previousIds.length - 1]
    try {
      setPair(await fetchCalibrationPair(previousId))
      setAnsweredIds(previousIds.slice(0, -1))
      setStatus('ready')
    } catch (error) {
      handleFailure(error)
    }
  }, [answeredIds, pair, handleFailure])

  return { pair, progress, status, answer, goBack, canGoBack: answeredIds.some((id) => id !== pair?.pair_id) }
}
