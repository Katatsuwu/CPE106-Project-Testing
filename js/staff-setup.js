import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { supabaseUrl, supabaseAnonKey } from "./supabase-config.js";

const client = createClient(supabaseUrl, supabaseAnonKey, { auth: { flowType: "implicit" } });
const form = document.getElementById("setupForm");
const message = document.getElementById("setupMessage");
const params = new URLSearchParams(location.hash.slice(1));
const errorDescription = params.get("error_description");
const errorCode = params.get("error_code");

function show(text, error = false) {
  message.textContent = text;
  message.style.color = error ? "#ffe2a8" : "#fff";
}

if (errorDescription || errorCode) {
  show(errorDescription || `Invitation error: ${errorCode}`, true);
} else {
  const { data, error } = await client.auth.getSession();
  if (error) {
    show(error.message, true);
  } else if (data.session) {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
    form.hidden = false;
    show(`Invitation accepted for ${data.session.user.email}. Choose a password to finish setup.`);
  } else {
    show("No active invitation was found. Ask the administrator to send you a fresh invite.", true);
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const password = document.getElementById("newPassword").value;
  const confirmation = document.getElementById("confirmPassword").value;
  if (password !== confirmation) return show("The passwords do not match.", true);
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  show("Saving password…");
  const { error } = await client.auth.updateUser({ password });
  button.disabled = false;
  if (error) return show(error.message, true);
  form.reset();
  form.hidden = true;
  show("Password saved. You can now sign in to the Cardinal Queue staff console.");
});
