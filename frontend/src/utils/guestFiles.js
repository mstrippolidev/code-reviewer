import inventoryCache from '../assets/guest-examples/inventory_cache.py?raw'
import orderService from '../assets/guest-examples/order_service.py?raw'
import paymentProcessor from '../assets/guest-examples/payment_processor.py?raw'
import reportUtils from '../assets/guest-examples/report_utils.py?raw'
import temperatureReadings from '../assets/guest-examples/temperature_readings.py?raw'

export const MAX_GUEST_FILES = 5 // mirrors api/schemas/reviews.py's MAX_GUEST_FILES
export const MAX_GUEST_FILE_LINES = 750

const EXAMPLES_FOLDER = 'examples'
const UPLOADS_FOLDER = 'uploads'

export const GUEST_EXAMPLE_FILES = [
  { path: `${EXAMPLES_FOLDER}/order_service.py`, content: orderService },
  { path: `${EXAMPLES_FOLDER}/inventory_cache.py`, content: inventoryCache },
  { path: `${EXAMPLES_FOLDER}/report_utils.py`, content: reportUtils },
  { path: `${EXAMPLES_FOLDER}/payment_processor.py`, content: paymentProcessor },
  { path: `${EXAMPLES_FOLDER}/temperature_readings.py`, content: temperatureReadings },
]

export class GuestUploadError extends Error {}

export async function readGuestUpload(file) {
  if (!file.name.endsWith('.py')) {
    throw new GuestUploadError(`${file.name} is not a Python (.py) file.`)
  }
  const content = await file.text()
  if (content.trim() === '') {
    throw new GuestUploadError(`${file.name} is empty.`)
  }
  const lineCount = countLines(content)
  if (lineCount > MAX_GUEST_FILE_LINES) {
    throw new GuestUploadError(
      `${file.name} has ${lineCount.toLocaleString()} lines — guest reviews accept files up to ${MAX_GUEST_FILE_LINES.toLocaleString()} lines.`
    )
  }
  return { path: `${UPLOADS_FOLDER}/${file.name}`, content }
}

export function guestTreeFiles(paths) {
  return paths.map((path) => ({
    path,
    status: 'indexed',
    statusReason: path.startsWith(`${UPLOADS_FOLDER}/`) ? 'Uploaded from your computer' : 'Example file',
  }))
}

function countLines(content) {
  const lines = content.split('\n')
  return content.endsWith('\n') ? lines.length - 1 : lines.length
}
