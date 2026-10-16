// Telegram bot → "update the site now". Cloudflare Worker, deployed by scripts/deploy_telegram_bot.py.
//
// Telegram POSTs every message to this Worker (webhook). It only acts when the request carries our
// webhook secret AND the sender's Telegram id is in ALLOWED_IDS; anything else gets a silent 200.
//   /update  → starts the "Sync Instagram and publish site" workflow (workflow_dispatch on main)
//   /status  → the last site run: what started it, when, and how it ended
// Secrets (set by the deploy script, never in this file): BOT_TOKEN, WEBHOOK_SECRET, GH_PAT
// (fine-grained, only-vans, Actions read & write), ALLOWED_IDS (comma-separated Telegram user ids).

const REPO = "zoobuv101/only-vans";
const WORKFLOW = "site.yml";
const GH = { "Accept": "application/vnd.github+json", "User-Agent": "only-vans-telegram-bot",
             "X-GitHub-Api-Version": "2022-11-28" };

export default {
  async fetch(req, env) {
    if (req.method !== "POST" || req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)
      return new Response("ok");
    const msg = (await req.json().catch(() => ({}))).message;
    if (!msg || !env.ALLOWED_IDS.split(",").map(s => s.trim()).includes(String(msg.from?.id)))
      return new Response("ok");
    const cmd = (msg.text || "").trim().split(/[\s@]/)[0].toLowerCase();
    let reply;
    try {
      if (cmd === "/update" || cmd === "update") reply = await update(env);
      else if (cmd === "/status" || cmd === "status") reply = await status(env);
      else reply = "Send /update to check Instagram and rebuild only-vans.uk now, or /status for the last run.";
    } catch (e) {
      reply = `Something went wrong: ${e.message}`;
    }
    await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: msg.chat.id, text: reply, disable_web_page_preview: true }),
    });
    return new Response("ok");  // always 200, or Telegram keeps re-sending the message
  },
};

async function update(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST", headers: { ...GH, "Authorization": `Bearer ${env.GH_PAT}` },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) return `GitHub refused the update (HTTP ${r.status}). /status shows the last run.`;
  return "Update started: checking Instagram now. New posts are usually live in 2–3 minutes. Send /status to see how it went.";
}

async function status(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=1`,
                        { headers: { ...GH, "Authorization": `Bearer ${env.GH_PAT}` } });
  if (!r.ok) return `Couldn't read GitHub (HTTP ${r.status}).`;
  const run = (await r.json()).workflow_runs?.[0];
  if (!run) return "No runs yet.";
  const when = new Date(run.run_started_at || run.created_at).toLocaleString("en-GB", {
    timeZone: "Europe/London", weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  const why = { schedule: "scheduled", workflow_dispatch: "manual / Telegram", push: "code change" }[run.event] || run.event;
  const how = run.status === "completed" ? (run.conclusion === "success" ? "✅ succeeded" : `❌ ${run.conclusion}`)
                                         : `⏳ ${run.status.replace("_", " ")}`;
  return `Last run: ${why}, ${when}, ${how}.\n${run.html_url}`;
}
