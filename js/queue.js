const nowServing = document.getElementById("nowServing");
const waitingList = document.getElementById("waitingList");
const lookupResult = document.getElementById("lookupResult");

function loadDemoQueue() {
  const records = JSON.parse(localStorage.getItem("cardinalQueueDemoRecords") || "[]");
  const waiting = records.filter(r => r.status === "waiting").slice(-9);

  waitingList.innerHTML = "";

  if (!waiting.length) {
    waitingList.innerHTML = "<div style='grid-column:1/-1;background:transparent;'>No waiting queue yet.</div>";
    return;
  }

  waiting.forEach(record => {
    const item = document.createElement("div");
    item.textContent = record.queueNumber;
    waitingList.appendChild(item);
  });
}

document.getElementById("checkBtn").addEventListener("click", () => {
  const query = document.getElementById("queueLookup").value.trim().toUpperCase();
  const records = JSON.parse(localStorage.getItem("cardinalQueueDemoRecords") || "[]");
  const record = records.find(r => r.queueNumber === query);

  if (!query) {
    lookupResult.textContent = "Please enter a queue number.";
  } else if (!record) {
    lookupResult.textContent = "Queue number not found.";
  } else {
    lookupResult.innerHTML =
      "<strong>" + record.queueNumber + "</strong><br>" +
      "Service: " + record.service + "<br>" +
      "Status: " + record.status.toUpperCase();
  }
});

loadDemoQueue();
setInterval(loadDemoQueue, 1000);

// FUTURE FIREBASE INTEGRATION:
// Replace the localStorage demo functions with Firebase listeners so
// Python Admin, Kiosk, TV, and User Portal all read/write the same data.
