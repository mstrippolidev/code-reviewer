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
      const event = extractEvent(rawEvent)
      if (event !== null) {
        yield event
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}

function extractEvent(rawEvent) {
  const lines = rawEvent.split('\n')
  const dataLines = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice('data:'.length).trimStart())
  if (dataLines.length === 0) {
    return null
  }
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const type = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
  return { type, data: dataLines.join('\n') }
}
