"use strict";
const $ = id => document.getElementById(id);
let selected = "users", userPage = 1, sessionPage = 1, query = "", snapshot = null;
let loading = false, loggedIn = false, generation = 0;
const labels = {valid:"有效", expired:"已过期", revoked:"已撤销", active:"可用"};
function loginScreen() {
  generation++;
  loggedIn = false; snapshot = null;
  $("login").hidden = false; $("board").hidden = true;
  $("table-body").replaceChildren(); $("username").focus();
  clearHash();
}
function clearHash() {
  $("hash-password").value=""; $("hash-output").value="";
  $("hash-result").hidden=true; $("hash-message").textContent="";
  $("hash-message").className="muted";
}
function date(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai", hour12:false});
}
function render() {
  const data = snapshot[selected], size = snapshot.page_size;
  $("users-tab").classList.toggle("selected", selected === "users");
  $("sessions-tab").classList.toggle("selected", selected === "sessions");
  const headings = selected === "users" ? ["ID", "用户名", "账号状态", "已查看欢迎页", "注册时间（北京时间）"] : ["ID", "用户名", "会话状态", "创建时间", "到期时间", "撤销时间"];
  const head = document.createElement("tr");
  headings.forEach(title => {const th = document.createElement("th"); th.textContent=title; head.append(th);});
  $("table-head").replaceChildren(head);
  const body = document.createDocumentFragment();
  data.items.forEach(item => {
    const tr = document.createElement("tr");
    const values = selected === "users" ? [item.id,item.username,item.status,item.seen_welcome ? "是" : "否",date(item.created_at)] : [item.id,item.username,item.state,date(item.created_at),date(item.expires_at),date(item.revoked_at)];
    values.forEach((value,i) => {
      const td = document.createElement("td");
      if (i === 2) {
        const badge = document.createElement("span"); badge.className="badge" + (["active","valid"].includes(value) ? " good" : value === "revoked" ? " bad" : "");
        badge.textContent=labels[value] || value; td.append(badge);
      } else td.textContent=String(value);
      tr.append(td);
    }); body.append(tr);
  });
  if (!data.items.length) {const tr=document.createElement("tr"), td=document.createElement("td"); td.colSpan=headings.length; td.className="empty"; td.textContent=query ? "没有找到匹配的用户名" : "暂无记录"; tr.append(td); body.append(tr);}
  $("table-body").replaceChildren(body);
  const pages = Math.max(1, Math.ceil(data.total/size));
  $("page-info").textContent=`共 ${data.total} 条 · 第 ${data.page} / ${pages} 页 · 每页 ${size} 条`;
  $("previous").disabled=data.page<=1; $("next").disabled=data.page>=pages;
}
async function refresh() {
  if (loading) return;
  loading=true; $("refresh").disabled=true;
  const currentGeneration=generation;
  try {
    const params=new URLSearchParams({q:query,user_page:userPage,session_page:sessionPage});
    const response=await fetch("/api/dashboard?"+params, {cache:"no-store", signal:AbortSignal.timeout(12000)});
    if(currentGeneration!==generation)return;
    if (response.status===401) {loginScreen(); return;}
    if (!response.ok) throw new Error("读取失败，稍后自动重试。上次数据仅供参考。");
    const result=await response.json();
    if(currentGeneration!==generation)return;
    snapshot=result; loggedIn=true;
    $("login").hidden=true; $("board").hidden=false; $("board-error").hidden=true;
    $("admin-name").textContent=snapshot.username;
    [["total-users","total_users"],["active-users","active_users"],["today-users","today_users"],["valid-sessions","valid_sessions"]].forEach(([id,key]) => $(id).textContent=snapshot.stats[key]);
    $("users-count").textContent=snapshot.users.total; $("sessions-count").textContent=snapshot.sessions.total;
    $("updated").textContent="更新于 "+date(snapshot.updated_at);
    render();
  } catch (error) {
    if(currentGeneration!==generation)return;
    if (loggedIn) {$("board-error").textContent=error.message; $("board-error").hidden=false;}
    else {$("login-error").textContent="暂时无法读取数据，请稍后登录重试。";}
  } finally {loading=false; $("refresh").disabled=false;}
}
$("login-form").addEventListener("submit", async event => {
  event.preventDefault(); $("login-button").disabled=true; $("login-error").textContent="";
  try {
    const response=await fetch("/api/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:$("username").value,password:$("password").value}),signal:AbortSignal.timeout(12000)});
    const result=await response.json();
    if (!response.ok) throw new Error(result.detail || "登录失败");
    $("password").value=""; userPage=1; sessionPage=1; query=""; $("search").value="";
    loggedIn=true; $("login").hidden=true; $("board").hidden=false; await refresh();
  } catch (error) {$("login-error").textContent=error.message;}
  finally {$("login-button").disabled=false;}
});
$("logout").addEventListener("click", async () => {
  try {const response=await fetch("/api/logout",{method:"POST",signal:AbortSignal.timeout(12000)}); if(!response.ok) throw new Error(); loginScreen();}
  catch {$("board-error").textContent="退出失败，请重试。"; $("board-error").hidden=false;}
});
$("refresh").addEventListener("click",refresh);
$("search-form").addEventListener("submit",event => {event.preventDefault(); if(loading)return; query=$("search").value; userPage=sessionPage=1; refresh();});
$("search").addEventListener("search",() => {if(!$("search").value&&!loading){query="";userPage=sessionPage=1;refresh();}});
["users","sessions"].forEach(name => $(name+"-tab").addEventListener("click",()=>{selected=name;if(snapshot)render();}));
function page(delta) {if(loading)return; if(selected==="users")userPage+=delta;else sessionPage+=delta;refresh();}
$("previous").addEventListener("click",()=>page(-1)); $("next").addEventListener("click",()=>page(1));
$("hash-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const currentGeneration=generation;
  const body=JSON.stringify({password:$("hash-password").value});
  clearHash(); $("hash-generate").disabled=true; $("hash-message").textContent="正在生成…";
  try {
    const response=await fetch("/api/password-hash",{method:"POST",headers:{"Content-Type":"application/json"},body,signal:AbortSignal.timeout(12000)});
    if(currentGeneration!==generation)return;
    if(response.status===401){loginScreen();return;}
    const result=await response.json();
    if(currentGeneration!==generation)return;
    if(!response.ok)throw new Error(typeof result.detail==="string" ? result.detail : "生成失败，请重试");
    $("hash-output").value=result.password_hash; $("hash-result").hidden=false;
    $("hash-message").textContent="已生成；请复制完整结果。数据库未发生修改。";
  } catch(error) {
    if(currentGeneration!==generation)return;
    $("hash-message").textContent=error.message; $("hash-message").className="error";
  } finally {$("hash-generate").disabled=false;}
});
$("hash-copy").addEventListener("click",async()=>{
  const output=$("hash-output");
  try {
    if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(output.value);
    else {output.focus();output.select();if(!document.execCommand("copy"))throw new Error("copy");}
    $("hash-message").textContent="已复制哈希。";
  } catch {output.focus();output.select();$("hash-message").textContent="已选中结果，请按 ⌘C（Windows：Ctrl+C）复制。";}
});
$("hash-clear").addEventListener("click",clearHash);
setInterval(()=>{if(loggedIn&&!document.hidden)refresh();},10000);
document.addEventListener("visibilitychange",()=>{if(loggedIn&&!document.hidden)refresh();});
refresh();
