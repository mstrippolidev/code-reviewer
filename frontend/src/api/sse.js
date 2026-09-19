export async function* parseEventStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      return
    }
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = extractEventData(rawEvent)
      if (data !== null) {
        yield data
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}

function extractEventData(rawEvent) {
  const dataLines = rawEvent
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trimStart())
  return dataLines.length > 0 ? dataLines.join('\n') : null
}
