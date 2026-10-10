import { call, isSupabaseConfigured, listenPublicQueue } from "./supabase-client.js";

const nowServing = document.getElementById("nowServing");
const waitingList = document.getElementById("waitingList");
const servingList = document.getElementById("servingList");
const lookupResult = document.getElementById("lookupResult");
const windowLabel = document.getElementById("windowLabel");

function message(text, kind = "") {
  lookupResult.replaceChildren();
  lookupResult.className = `lookup-result ${kind}`;
  lookupResult.textContent = text;
}

function paint(records) {
  const serving = records.filter(record => record.status === "Serving").sort((a, b) => String(a.window).localeCompare(String(b.window)));
  const waiting = records.filter(record => record.status === "Waiting").sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
  const serviceCounts = {
    enrollment: waiting.filter(record => record.service === "Enrollment").length,
    payment: waiting.filter(record => record.service === "Payment").length,
    forms: waiting.filter(record => ["Form 137", "SF9", "Other"].includes(record.service)).length,
  };
  document.getElementById("countEnrollment").textContent = serviceCounts.enrollment;
  document.getElementById("countPayment").textContent = serviceCounts.payment;
  document.getElementById("countForms").textContent = serviceCounts.forms;
  nowServing.textContent = serving.length ? serving[0].queueNumber : "—";
  nowServing.classList.toggle("is-empty", !serving.length);
  windowLabel.textContent = serving.length
    ? `${serving[0].service} · WINDOW ${serving[0].window}`
    : "No queue is being served";
  servingList.replaceChildren();
  for (const record of serving.slice(1)) {
    const item = document.createElement("div");
    item.className = "serving-card";
    item.textContent = `${record.queueNumber} · ${record.service} · Window ${record.window}`;
    servingList.append(item);
  }
  waitingList.replaceChildren();
  if (!waiting.length) {
    const empty = document.createElement("p");
    empty.className = "queue-empty";
    empty.textContent = "No waiting queues right now.";
    waitingList.append(empty);
    return;
  }
  for (const record of waiting.slice(0, 12)) {
    const item = document.createElement("div");
    item.className = `waiting-card ${serviceClass(record.service)}`;
    item.textContent = `${record.queueNumber} · ${record.service} · Window ${record.window}`;
    waitingList.append(item);
  }
}

function serviceClass(service) {
  if (service === "Payment") return "service-payment";
  if (["Form 137", "SF9", "Other"].includes(service)) return "service-forms";
  return "service-enrollment";
}

async function lookup() {
  const queueNumber = document.getElementById("queueLookup").value.trim().toUpperCase();
  const accessCode = document.getElementById("queueCode").value.trim();
  const queueId = document.getElementById("queueLookup").dataset.queueId || "";
  if (!queueNumber || !accessCode) return message("Enter both your queue number and private ticket code.", "error");
  if (!isSupabaseConfigured) return message("Queue lookup is unavailable until Supabase is configured.", "error");
  message("Checking your queue…");
  try {
    const { data } = await call("lookupQueue", { queueNumber, accessCode, ...(queueId ? { queueId } : {}) });
    lookupResult.replaceChildren();
    lookupResult.className = "lookup-result";
    const title = document.createElement("strong");
    title.textContent = `${data.queueNumber} · ${data.status}`;
    const detail = document.createElement("span");
    detail.textContent = `${data.service} · Window ${data.window} · ${data.ahead} ahead`;
    lookupResult.append(title, document.createElement("br"), detail);
  } catch (error) {
    message(error.message || "We could not find that queue. Check the ticket details and try again.", "error");
  }
}

document.getElementById("checkBtn").addEventListener("click", lookup);
document.getElementById("queueCode").addEventListener("keydown", event => { if (event.key === "Enter") lookup(); });

if (!isSupabaseConfigured) {
  message("Connect Supabase to show live queues.");
  const notice = document.createElement("p");
  notice.className = "queue-empty";
  notice.textContent = "Live queue display will appear after Supabase setup.";
  waitingList.replaceChildren(notice);
} else {
  listenPublicQueue(paint, () => { waitingList.textContent = "Live queue connection lost. Reconnecting…"; });
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.has("queue")) {
    document.getElementById("queueLookup").value = params.get("queue");
    document.getElementById("queueCode").value = params.get("code") || "";
    document.getElementById("queueLookup").dataset.queueId = params.get("id") || "";
    if (params.has("code")) lookup();
  }
}
