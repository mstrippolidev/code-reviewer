import { useEffect, useState } from 'react'
import { fetchAgents } from '../api/client'

export function useAgentCatalog(token) {
  const [agentsByCodeKey, setAgentsByCodeKey] = useState({})
  const [order, setOrder] = useState([])

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const agents = await fetchAgents(token)
        if (!active) {
          return
        }
        setAgentsByCodeKey(Object.fromEntries(agents.map((agent) => [agent.code_key, agent])))
        setOrder(agents.map((agent) => agent.code_key))
      } catch {
        // The catalog only enriches an agent's label; a review stays readable without it.
      }
    }

    load()
    return () => {
      active = false
    }
  }, [token])

  return { agentsByCodeKey, order }
}
