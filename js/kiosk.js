const homeView = document.getElementById("homeView");
const formView = document.getElementById("formView");
const ticketView = document.getElementById("ticketView");
const queueForm = document.getElementById("queueForm");

let selectedService = "";

function show(view) {
  [homeView, formView, ticketView].forEach(v => v.classList.remove("active"));
  view.classList.add("active");
  window.scrollTo(0, 0);
}

document.querySelectorAll(".service-btn").forEach(button => {
  button.addEventListener("click", () => {
    selectedService = button.dataset.service;
    show(formView);
    document.getElementById("fullName").focus();
  });
});

document.getElementById("returnBtn").addEventListener("click", () => show(homeView));
document.getElementById("ticketReturnBtn").addEventListener("click", () => {
  queueForm.reset();
  show(homeView);
});

function nextLocalQueueNumber() {
  const current = Number(localStorage.getItem("cardinalQueueDemoCounter") || "0") + 1;
  localStorage.setItem("cardinalQueueDemoCounter", String(current));
  return "A" + String(current).padStart(3, "0");
}

queueForm.addEventListener("submit", event => {
  event.preventDefault();

  const name = document.getElementById("fullName").value.trim();
  const education = document.getElementById("education").value;
  const email = document.getElementById("email").value.trim();
  const queueNumber = nextLocalQueueNumber();

  // Demo-only local record. Replace this section with your Firebase write.
  const queueRecord = {
    queueNumber,
    service: selectedService,
    name,
    education,
    email,
    status: "waiting",
    createdAt: new Date().toISOString()
  };

  const records = JSON.parse(localStorage.getItem("cardinalQueueDemoRecords") || "[]");
  records.push(queueRecord);
  localStorage.setItem("cardinalQueueDemoRecords", JSON.stringify(records));

  document.getElementById("ticketNumber").textContent = queueNumber;
  document.getElementById("ticketService").textContent = selectedService;
  document.getElementById("ticketName").textContent = name;

  show(ticketView);
});
