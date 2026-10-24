/** Downloads `data` as a pretty-printed JSON file, entirely in the browser. */
export function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  // Revoke later: some browsers cancel the download if the URL disappears at once
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
