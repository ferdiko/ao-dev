export function getIconByExtension(filename: string, pdfIconUri?: string): string {
    if (!filename || typeof filename !== 'string') return '📁';
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    if (["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp"].includes(ext)) return '🖼️';
    if (["pdf"].includes(ext)) return pdfIconUri ? `<img src=\"${pdfIconUri}\" alt=\"PDF\" style=\"width:20px;height:20px;vertical-align:middle;display:inline-block;margin-top:0;margin-bottom:0;\" />` : '📄';
    if (["doc", "docx"].includes(ext)) return '📃';
    if (["xls", "xlsx"].includes(ext)) return '📊';
    if (["ppt", "pptx"].includes(ext)) return '📈';
    if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return '🗜️';
    if (["txt", "md"].includes(ext)) return '📝';
    if (["mp3", "wav", "ogg"].includes(ext)) return '🎵';
    if (["mp4", "avi", "mov", "mkv", "webm"].includes(ext)) return '🎬';
    return '📁';
}