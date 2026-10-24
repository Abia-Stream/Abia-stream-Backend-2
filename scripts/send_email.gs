/**
 * Abia Stream email relay (Google Apps Script).
 * Sends the backend's verification / password-reset emails from this Google
 * account's Gmail. Used when EMAIL_PROVIDER=apps_script.
 *
 * Setup (once):
 *   1. https://script.google.com -> New project; paste this file over Code.gs.
 *   2. Project Settings -> Script Properties -> add EMAIL_SECRET = a long random
 *      string (the same value goes in Render as APPS_SCRIPT_EMAIL_SECRET).
 *   3. Deploy -> New deployment -> type "Web app"; Execute as: Me;
 *      Who has access: Anyone. Authorize when asked.
 *   4. Copy the Web app URL (ends in /exec) into Render as APPS_SCRIPT_EMAIL_URL.
 * After editing this code, use Deploy -> Manage deployments -> Edit -> New
 * version, so the same URL serves the new code.
 *
 * Limit: a personal Gmail account can email about 100 recipients a day.
 */
function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ok: false, error: 'invalid JSON'});
  }

  var secret = PropertiesService.getScriptProperties().getProperty('EMAIL_SECRET');
  if (!secret || body.secret !== secret) {
    return reply({ok: false, error: 'unauthorized'});
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.to || '') || !body.subject || !body.html) {
    return reply({ok: false, error: 'to, subject and html are required'});
  }
  if (MailApp.getRemainingDailyQuota() < 1) {
    return reply({ok: false, error: 'daily Gmail quota used up'});
  }

  MailApp.sendEmail({
    to: body.to,
    subject: body.subject,
    htmlBody: body.html,
    name: body.name || 'Abia Stream',
    noReply: false
  });
  return reply({ok: true, remaining: MailApp.getRemainingDailyQuota()});
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
