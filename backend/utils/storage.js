// ═══════════════════════════════════════
// utils/storage.js — Supabase Storage helpers
// ═══════════════════════════════════════
const fs = require('fs');

/**
 * Upload a multer file to Supabase Storage bucket 'job-files'.
 * Returns a 24-hour signed URL.
 */
async function uploadToStorage(supabase, file, pathPrefix) {
  const fileBuffer = fs.readFileSync(file.path);
  const fileName   = `${pathPrefix}/${file.filename}`;

  const { error } = await supabase.storage
    .from('job-files')
    .upload(fileName, fileBuffer, {
      contentType: file.mimetype,
      upsert: false
    });

  if (error) throw new Error(`Storage upload failed: ${error.message}`);

  // Clean up temp file
  fs.unlinkSync(file.path);

  const { data: signedUrl } = await supabase.storage
    .from('job-files')
    .createSignedUrl(fileName, 86400);  // 24 hours

  return signedUrl?.signedUrl || null;
}

/**
 * Generate a fresh signed URL for an existing file path.
 */
async function refreshSignedUrl(supabase, filePath, expiresIn = 86400) {
  const { data } = await supabase.storage
    .from('job-files')
    .createSignedUrl(filePath, expiresIn);
  return data?.signedUrl;
}

module.exports = { uploadToStorage, refreshSignedUrl };
