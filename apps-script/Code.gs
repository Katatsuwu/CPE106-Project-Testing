function jsonOutput(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

function doGet() {
  return jsonOutput({ ok: true, service: "Cardinal Queue email relay" });
}

function doPost(e) {
  try {
    const raw = e && e.postData && e.postData.contents || "";
    if (!raw || raw.length > 12000) return jsonOutput({ ok: false, error: "Invalid request." });

    const request = JSON.parse(raw);
    const ts = Number(request.ts);
    const message = request.message;
    const secret = PropertiesService.getScriptProperties().getProperty("RELAY_SECRET");
    if (!secret || !Number.isInteger(ts) || Math.abs(Math.floor(Date.now() / 1000) - ts) > 300 || !message) {
      return jsonOutput({ ok: false, error: "Invalid or expired request." });
    }

    const signature = Utilities.base64EncodeWebSafe(
      Utilities.computeHmacSha256Signature(`${ts}.${JSON.stringify(message)}`, secret, Utilities.Charset.UTF_8)
    ).replace(/=+$/, "");
    if (!constantTimeEqual(signature, request.signature)) return jsonOutput({ ok: false, error: "Invalid request signature." });

    if (!/^[a-f0-9-]{36}:(three_away|ready|ticket_details)$/.test(String(message.id || "")) ||
        !/^\S+@\S+\.\S+$/.test(String(message.to || "")) ||
        !message.subject || String(message.subject).length > 180 ||
        !message.body || String(message.body).length > 4000) {
      return jsonOutput({ ok: false, error: "Invalid message." });
    }

    const key = `sent_${message.id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
    const cache = CacheService.getScriptCache();
    const lock = LockService.getScriptLock();
    lock.waitLock(5000);
    try {
      if (cache.get(key)) return jsonOutput({ ok: true, duplicate: true });
      cache.put(key, "sending", 3600);
    } finally {
      lock.releaseLock();
    }

    try {
      MailApp.sendEmail({
        to: String(message.to),
        subject: String(message.subject),
        body: String(message.body),
        name: "Cardinal Queue",
      });
      cache.put(key, "sent", 21600);
      return jsonOutput({ ok: true });
    } catch (error) {
      cache.remove(key);
      throw error;
    }
  } catch (error) {
    console.error("Relay error:", error && error.message || "Unknown error");
    return jsonOutput({ ok: false, error: "Email delivery failed." });
  }
}
