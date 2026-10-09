import { call, isSupabaseConfigured } from "./supabase-client.js";

const views = ["homeView", "formView", "ticketView"].map(id => document.getElementById(id));
const form = document.getElementById("queueForm");
let selectedService = "";
let returnTimer = null;

function show(viewId) {
  for (const view of views) view.classList.toggle("active", view.id === viewId);
  window.scrollTo(0, 0);
}

function setMessage(text, error = false) {
  const el = document.getElementById("ticketMessage");
  el.textContent = text;
  el.classList.toggle("error", error);
}

function selectService(button) {
  selectedService = button.dataset.service;
  show("formView");
  document.getElementById("fullName").focus();
}
document.querySelector(".service-list").addEventListener("click", event => {
  const button = event.target.closest(".service-btn");
  if (button) selectService(button);
});
document.getElementById("returnBtn").addEventListener("click", () => { form.reset(); show("homeView"); });
function returnToKiosk() {
  if (returnTimer) clearTimeout(returnTimer);
  form.reset();
  const qr = document.getElementById("ticketQr");
  const link = document.createElement("a");
  link.href = "queue.html";
  link.setAttribute("aria-label", "Open the live queue monitor");
  const image = document.createElement("img");
  image.src = "assets/queue_qr.png";
  image.alt = "Scan to open the Cardinal Queue monitor";
  link.append(image);
  qr.replaceChildren(link);
  show("homeView");
}
document.getElementById("ticketReturnBtn").addEventListener("click", returnToKiosk);

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!isSupabaseConfigured) {
    alert("The kiosk is not connected yet. Add the Supabase project URL and publishable key, then deploy the backend.");
    return;
  }
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "REGISTERING…";
  try {
    const values = new FormData(form);
    const { data } = await call("registerQueue", {
      fullName: String(values.get("fullName")).trim(),
      education: String(values.get("education")),
      email: String(values.get("email")).trim(),
      service: selectedService,
    });
    document.getElementById("ticketNumber").textContent = data.queueNumber;
    document.getElementById("ticketService").textContent = selectedService;
    document.getElementById("ticketWindow").textContent = `WINDOW ${data.window}`;
    const emailSent = data.queueDetailsEmailSent === true;
    setMessage(emailSent
      ? "A copy of your queue details has been sent to your email."
      : "Your queue details email could not be sent. Please keep these ticket details visible.", !emailSent);
    const monitorUrl = new URL("queue.html", location.href);
    monitorUrl.hash = new URLSearchParams({ queue: data.queueNumber, code: data.accessCode, id: data.queueId }).toString();
    const qr = document.getElementById("ticketQr");
    if (window.QRCode?.toCanvas) {
      const canvas = document.createElement("canvas");
      try {
        await window.QRCode.toCanvas(canvas, monitorUrl.href, { width: 180, margin: 2, errorCorrectionLevel: "M" });
        qr.replaceChildren(canvas);
      } catch {
        // Keep the supplied public monitor QR visible when the CDN generator is unavailable.
      }
    }
    show("ticketView");
    if (returnTimer) clearTimeout(returnTimer);
    returnTimer = setTimeout(returnToKiosk, 60000);
  } catch (error) {
    alert(error.message || "Registration could not be completed. Please try again.");
  } finally {
    submit.disabled = false;
    submit.textContent = "SUBMIT";
  }
});

if (!isSupabaseConfigured) {
  const banner = document.createElement("p");
  banner.className = "setup-notice";
  banner.textContent = "Setup required: Supabase has not been connected. This kiosk will not accept or store registrations yet.";
  document.getElementById("homeView").append(banner);
} else {
  call("listServices").then(({ data }) => {
    const serviceList = document.querySelector(".service-list");
    serviceList.replaceChildren();
    const originalKioskServices = new Set(["Enrollment", "Form 137", "SF9", "Other"]);
    for (const service of data.services.filter(item => item.active && originalKioskServices.has(item.name))) {
      const button = document.createElement("button");
      button.className = "service-btn";
      button.dataset.service = service.name;
      button.type = "button";
      button.textContent = service.name.toUpperCase();
      serviceList.append(button);
    }
    if (!serviceList.childElementCount) serviceList.textContent = "No services are currently available.";
  }).catch(() => {});
}
