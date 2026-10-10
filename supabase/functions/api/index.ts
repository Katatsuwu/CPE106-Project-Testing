import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type", "Access-Control-Allow-Methods": "POST, OPTIONS" };
const services = ["Enrollment", "Payment", "Form 137", "SF9", "Other"];
const clean = (v: unknown, n: number) => String(v ?? "").trim().slice(0, n);
const errorMessage = (error: unknown) => {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  if (error && typeof error === "object") {
    const detail = error as Record<string, unknown>;
    for (const field of ["message", "details", "hint", "error_description"]) {
      if (typeof detail[field] === "string" && detail[field].trim()) return detail[field] as string;
    }
    try { return JSON.stringify(error); } catch { /* use the generic message below */ }
  }
  return "The request failed unexpectedly.";
};
const isoDay = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const client = () => createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const queueShape = (q: any) => ({ id:q.id, queueNumber:q.queue_number, queueSequence:q.queue_sequence, userId:q.user_id, fullName:q.full_name, education:q.education, email:q.email, service:q.service, serviceKey:q.service_key, window:q.service_window, status:q.status, dateKey:q.date_key, createdAt:q.created_at, serviceTime:q.service_time, completionTime:q.completion_time, calledBy:q.called_by });

async function signRelay(ts: number, message: Record<string, string>) {
  const secret = Deno.env.get("EMAIL_RELAY_SECRET");
  if (!secret) throw new Error("Email relay secret is not configured.");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${ts}.${JSON.stringify(message)}`)));
  let binary = "";
  for (const byte of signature) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sendNotification(db: any, q: any, kind: "three_away" | "ready" | "ticket_details", ticketDetails?: { fullName: string; education: string; accessCode: string }) {
  const relayUrl = Deno.env.get("EMAIL_RELAY_URL");
  const relaySecret = Deno.env.get("EMAIL_RELAY_SECRET");
  if (!relayUrl || !relaySecret) {
    console.error("Email notification skipped: relay settings are missing.");
    return false;
  }
  const id = `${q.id}:${kind}`;
  const ready = kind === "ready";
  const ticketDetailsEmail = kind === "ticket_details";
  const ticket = q.queue_number;
  const service = q.service;
  const window = q.service_window;
  const monitorUrl = new URL("https://katatsuwu.github.io/Cardinal-Queue/queue.html");
  if (ticketDetailsEmail && ticketDetails) monitorUrl.hash = new URLSearchParams({ queue:ticket, code:ticketDetails.accessCode, id:q.id }).toString();
  const message = {
    id,
    to: q.email,
    subject: ticketDetailsEmail ? `Your queue details — Cardinal Queue (${ticket})` : ready ? `Ticket ${ticket} is ready — Cardinal Queue` : `Ticket ${ticket}: 3 tickets ahead — Cardinal Queue`,
    body: ticketDetailsEmail
      ? `Hello ${ticketDetails?.fullName || ""},\n\nHere are your Cardinal Queue details:\nName: ${ticketDetails?.fullName || ""}\nEducation: ${ticketDetails?.education || ""}\nQueue number: ${ticket}\nService: ${service}\nService window: ${window}\nStatus: Waiting\nEmail: ${q.email}\n\nOpen this private queue link to check your status:\n${monitorUrl.href}\n\nPrivate ticket code: ${ticketDetails?.accessCode || ""}\nKeep this code private. The link contains it so your queue can open directly.`
      : ready
      ? `Your Cardinal Queue ticket ${ticket} for ${service} is ready to be served at Window ${window}. Please go to the window now.`
      : `Your Cardinal Queue ticket ${ticket} for ${service} at Window ${window} is about 3 tickets away. Please get ready. You can follow the live queue at https://katatsuwu.github.io/Cardinal-Queue/queue.html.`,
  };
  const { error: insertError } = await db.from("notifications").insert({ notification_id:id, queue_id:q.id, queue_number:ticket, email:q.email, type:kind, status:"Pending", attempts:0 });
  if (insertError) {
    if (insertError.code !== "23505") console.error("Could not queue email notification:", insertError.message);
    return false;
  }
  try {
    let lastError: Error | null = null;
    let attempts = 0;
    for (let attempt = 1; attempt <= 2; attempt++) {
      attempts = attempt;
      try {
        const ts = Math.floor(Date.now() / 1000);
        const signature = await signRelay(ts, message);
        const response = await fetch(relayUrl, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ ts, message, signature }) });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.ok !== true) throw new Error(result.error || `Relay returned HTTP ${response.status}.`);
        lastError = null;
        break;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error("Email delivery failed.");
      }
    }
    if (lastError) throw lastError;
    const { error } = await db.from("notifications").update({ status:"Sent", attempts, delivered_at:new Date().toISOString(), last_error:null }).eq("notification_id",id);
    if (error) console.error("Email sent but notification status update failed:", error.message);
    return true;
  } catch (error) {
    const detail = (error instanceof Error ? error.message : "Email delivery failed.").slice(0, 500);
    await db.from("notifications").update({ status:"Failed", attempts:2, last_error:detail }).eq("notification_id",id);
    console.error("Email notification failed:", detail);
    return false;
  }
}

async function sendThreeAwayForLane(db: any, service: string, window: number, dateKey: string) {
  const { data, error } = await db.from("queues").select("id,queue_number,email,service,service_window")
    .eq("date_key",dateKey).eq("service",service).eq("service_window",window).eq("status","Waiting")
    .order("created_at",{ascending:true}).order("id",{ascending:true});
  if (error) { console.error("Could not check three-away queue position:", error.message); return; }
  const candidate = data?.[3];
  if (candidate) await sendNotification(db,candidate,"three_away");
}

Deno.serve(async req => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });
  try {
    const body = await req.json(); const action = clean(body.action, 40); const db = client();
    const token = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
    let user: any = null; let role = "";
    if (token) {
      const { data, error } = await db.auth.getUser(token);
      if (!error) user = data.user;
      if (user) {
        const { data: member } = await db.from("staff").select("role,active").eq("staff_id", user.id).maybeSingle();
        if (member?.active && ["staff", "system_admin"].includes(member.role)) role = member.role;
      }
    }
    const requireStaff = (admin = false) => { if (!user || !role || (admin && role !== "system_admin")) throw new Error("An authorized staff account is required."); };
    const audit = async (name: string, id = "", detail: unknown = {}) => {
      const { error } = await db.from("audit_logs").insert({ staff_uid:user.id, role, action:name, record_id:id, detail });
      if (error) throw error;
    };
    if (action === "listServices") {
      const { data, error } = await db.from("services").select("name,active").order("name"); if (error) throw error;
      return json({ services: services.map(name => ({ name, active: data.find((s:any)=>s.name===name)?.active ?? true })) });
    }
    if (action === "registerQueue") {
      const fullName=clean(body.fullName,120), education=clean(body.education,60), email=clean(body.email,254).toLowerCase(), service=clean(body.service,40);
      if (!fullName || !education || !/^\S+@\S+\.\S+$/.test(email) || !services.includes(service)) throw new Error("Complete the form with a valid email and selected service.");
      const accessCode=Array.from(crypto.getRandomValues(new Uint8Array(18)),b=>"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"[b&63]).join("");
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(accessCode))),b=>b.toString(16).padStart(2,"0")).join("");
      const { data, error } = await db.rpc("register_queue", { p_full_name:fullName,p_education:education,p_email:email,p_service:service,p_access_hash:hash }); if (error) throw error;
      const queueDetailsEmailSent = await sendNotification(db, { id:data.queueId, queue_number:data.queueNumber, email, service, service_window:data.window }, "ticket_details", { fullName, education, accessCode });
      await sendThreeAwayForLane(db,service,Number(data.window),isoDay());
      return json({ ...data, accessCode, queueDetailsEmailSent });
    }
    if (action === "lookupQueue") {
      const number=clean(body.queueNumber,20).toUpperCase(), code=clean(body.accessCode,80), id=clean(body.queueId,100);
      if ((!number&&!id)||!code) throw new Error("Queue number and private ticket code are required.");
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(code))),b=>b.toString(16).padStart(2,"0")).join("");
      let query=db.from("queues").select("id,queue_number,service,service_window,status,date_key,created_at,access_hash"); query=id?query.eq("id",id):query.eq("queue_number",number);
      const { data, error }=await query.limit(1).maybeSingle(); if(error)throw error;
      if(!data||data.queue_number!==number||data.access_hash!==hash) throw new Error("No matching queue was found. Check your private ticket code.");
      let ahead=0;
      if(data.status==="Waiting") { const orderFilter="created_at.lt."+data.created_at+",and(created_at.eq."+data.created_at+",id.lt."+data.id+")"; const { count,error:e }=await db.from("queues").select("id",{count:"exact",head:true}).eq("date_key",data.date_key).eq("service",data.service).eq("service_window",data.service_window).eq("status","Waiting").or(orderFilter); if(e)throw e; ahead=count||0; }
      return json({ queueNumber:data.queue_number,service:data.service,window:data.service_window,status:data.status,ahead });
    }
    if (action === "profile") { requireStaff(); return json({ email:user.email, role, uid:user.id }); }
    if (action === "listQueues" || action === "getRecords" || action === "getReport") {
      requireStaff(); const day=clean(body.dateKey,10)||isoDay();
      let query=db.from("queues").select("*").eq("date_key",day).order("created_at",{ascending:action==="listQueues"});
      if(action==="listQueues") query=query.limit(500); else if(action==="getRecords") query=query.limit(1000);
      const { data,error }=await query; if(error)throw error;
      if(action==="listQueues") { if(!body.quiet)await audit("queues.view","",{dateKey:day}); return json({queues:(data||[]).map(queueShape)}); }
      if(action==="getRecords") { await audit("records.view","",{dateKey:day}); return json({records:(data||[]).map(queueShape)}); }
      const report:any={dateKey:day,total:data?.length||0,waiting:0,serving:0,completed:0,byService:{}};
      for(const q of data||[]) { report[q.status.toLowerCase()]++; report.byService[q.service]??={total:0,completed:0}; report.byService[q.service].total++; if(q.status==="Completed")report.byService[q.service].completed++; }
      return json(report);
    }
    if(action==="transitionQueue") {
      requireStaff(); const kind=clean(body.queueAction,30); if(!["callNext","complete","returnToWaiting"].includes(kind))throw new Error("Choose a valid queue action.");
      const id=body.queueId?clean(body.queueId,100):null; const win=body.window?Number(body.window):null;
      const { data,error }=await db.rpc("transition_queue",{p_action:kind,p_queue_id:id,p_window:win,p_staff_uid:user.id}); if(error)throw error;
      const q=queueShape(data); await audit(kind==="callNext"?"queue.called":kind==="complete"?"queue.completed":"queue.returned",q.id,{queueNumber:q.queueNumber,window:q.window});
      if(kind==="callNext") await sendNotification(db,data,"ready");
      if(data.status==="Waiting") await sendThreeAwayForLane(db,data.service,Number(data.service_window),data.date_key);
      return json({queue:q});
    }
    if(action==="saveService") {
      requireStaff(true); const name=clean(body.name,40); if(!services.includes(name))throw new Error("Choose a supported service.");
      const windows=[...new Set((Array.isArray(body.windows)?body.windows:[]).map(Number).filter(n=>Number.isInteger(n)&&n>0&&n<100))]; if(!windows.length)throw new Error("Choose at least one valid window.");
      const {error}=await db.from("services").update({active:body.active!==false,windows,updated_at:new Date().toISOString(),updated_by:user.id}).eq("name",name);if(error)throw error;
      await audit("service.updated",name,{name,active:body.active!==false,windows});return json({ok:true});
    }
    if(action==="listStaff") {
      requireStaff(true);const {data,error}=await db.from("staff").select("staff_id,name,email,role,active").order("name").limit(500);if(error)throw error;
      await audit("staff.listed");return json({staff:(data||[]).map((x:any)=>({id:x.staff_id,staffId:x.staff_id,name:x.name,email:x.email,role:x.role,active:x.active}))});
    }
    if(action==="setStaffRole") {
      requireStaff(true);const uid=clean(body.uid,128),nextRole=clean(body.role,30),name=clean(body.name,120);
      if(!uid||!["staff","system_admin","disabled"].includes(nextRole))throw new Error("Enter a valid staff user ID and role.");
      if(uid===user.id&&nextRole!=="system_admin")throw new Error("A system administrator cannot remove their own administrator role.");
      const {data,error}=await db.auth.admin.getUserById(uid);if(error||!data.user)throw new Error("Create the user in Supabase Authentication first.");
      const {error:writeError}=await db.from("staff").upsert({staff_id:uid,name,email:data.user.email||"",role:nextRole,active:nextRole!=="disabled",updated_at:new Date().toISOString()});if(writeError)throw writeError;
      await audit("staff.role_updated",uid,{role:nextRole});return json({ok:true});
    }
    if(action==="listLogs") { requireStaff(true);const {data,error}=await db.from("audit_logs").select("*").order("created_at",{ascending:false}).limit(200);if(error)throw error;await audit("logs.view");return json({logs:(data||[]).map((x:any)=>({id:x.id,staffUid:x.staff_uid,role:x.role,action:x.action,recordId:x.record_id,detail:x.detail,createdAt:x.created_at}))}); }
    return json({error:"Unknown action."},404);
  } catch(e) { return json({error:errorMessage(e)},400); }
});
