import { getIconByExtension } from './fileIcons';

/**
 * Generates the HTML for the attachments section in the edit dialog webview.
 * @param attachments Array of [filename, filepath] tuples
 * @param pdfIconUri URI for the PDF icon (or other icons as needed)
 * @returns HTML string for the attachments section
 */
export function generateAttachmentsHtml(
  attachments: [string, string][],
  pdfIconUri: string
): string {
  if (!attachments || attachments.length === 0) return '';
  return `<div class="attachments-list"><strong>Attachments:</strong><div class="attachments-row">` +
    attachments.map((a, idx) => {
      const icon = getIconByExtension(a[0], pdfIconUri);
      return `<div class="attachment-item">
        <span class="attachment-icon">${icon}</span>
        <a href="#" onclick="openAttachment(${idx});return false;" class="attachment-link">${a[0]}</a>
        <button class="attachment-remove" title="Remove" onclick="removeAttachment(${idx})">×</button>
      </div>`;
    }).join('') +
    `</div></div>`;
}
