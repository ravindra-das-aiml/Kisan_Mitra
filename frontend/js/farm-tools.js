const FARM_API="http://localhost:8000";
const f$=id=>document.getElementById(id);
function farmToken(){return localStorage.getItem("access_token")}
function authHeaders(json=true){const h={Authorization:`Bearer ${farmToken()}`};if(json)h["Content-Type"]="application/json";return h}
async function farmApi(path,opts={}){const r=await fetch(FARM_API+path,{...opts,headers:{...authHeaders(opts.body!==undefined),...(opts.headers||{})}});let d={};try{d=await r.json()}catch{}if(r.status===401){location.href="login.html";throw Error("Please log in again.")}if(!r.ok)throw Error(d.detail||"Request failed");return d}
function addChatBubble(text,kind){const box=f$("chatMessages"),el=document.createElement("div");el.className=`chat-bubble ${kind}`;el.textContent=text;box.appendChild(el);box.scrollTop=box.scrollHeight;return el}
function niceDate(value){return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"})}
async function sendChat(ev){
  ev.preventDefault();
  const input=f$("chatInput"),message=input.value.trim();
  if(!message)return;
  addChatBubble(message,"user");input.value="";f$("chatStatus").textContent=kmText("loading");
  const sendBtn=f$("chatForm").querySelector("button");sendBtn.disabled=true;
  const bubble=addChatBubble("","assistant");
  try{
    const response=await fetch(FARM_API+"/api/chat/stream",{
      method:"POST",headers:authHeaders(),
      body:JSON.stringify({message,language:kmLanguage(),crop:f$("chatCrop").value.trim()||null})
    });
    if(response.status===401){location.href="login.html";throw Error("Please log in again.")}
    if(!response.ok){let d={};try{d=await response.json()}catch{}throw Error(d.detail||"Request failed")}
    if(!response.body){bubble.textContent=await response.text();return}
    const reader=response.body.getReader(),decoder=new TextDecoder();
    while(true){
      const {value,done}=await reader.read();
      if(done)break;
      bubble.textContent+=decoder.decode(value,{stream:true});
      f$("chatMessages").scrollTop=f$("chatMessages").scrollHeight;
    }
    bubble.textContent+=decoder.decode();
    if(!bubble.textContent.trim())bubble.textContent=kmText("chatError");
    f$("chatStatus").textContent="";
  }catch(e){
    bubble.textContent=bubble.textContent.trim()?bubble.textContent+"\n"+e.message:`${kmText("chatError")} ${e.message}`;
    f$("chatStatus").textContent=e.message;
  }finally{sendBtn.disabled=false;input.focus()}
}
async function loadCalendar(){const host=f$("calendarEvents");try{const rows=await farmApi("/api/calendar");host.replaceChildren();if(!rows.length){const p=document.createElement("p");p.className="muted";p.textContent=kmText("noEvents");host.appendChild(p);return}for(const row of rows){const card=document.createElement("article");card.className="calendar-event";const info=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("p"),desc=document.createElement("p"),del=document.createElement("button");title.textContent=row.title;meta.className="muted";meta.textContent=`${niceDate(row.event_date)} · ${kmText(row.event_type)||row.event_type} · ${row.reminder_days_before} day(s) before`;desc.className="muted";desc.textContent=row.description||"";del.className="btn outline small-btn";del.type="button";del.textContent=kmText("delete");del.addEventListener("click",async()=>{const confirmMessage=window.kmTranslateText?await window.kmTranslateText("Delete this calendar activity?"):"Delete this calendar activity?";if(!confirm(confirmMessage))return;try{await farmApi(`/api/calendar/${row.id}`,{method:"DELETE"});loadCalendar()}catch(e){f$("calendarStatus").textContent=e.message}});info.append(title,meta);if(row.description)info.append(desc);card.append(info,del);host.appendChild(card)}}catch(e){host.textContent=e.message}}
async function addCalendarEvent(ev){ev.preventDefault();const status=f$("calendarStatus");status.textContent=kmText("loading");try{await farmApi("/api/calendar",{method:"POST",body:JSON.stringify({title:f$("eventTitle").value.trim(),description:f$("eventDescription").value.trim()||null,event_type:f$("eventType").value,event_date:f$("eventDate").value,reminder_days_before:Number(f$("reminderDays").value)})});f$("calendarForm").reset();f$("eventDate").min=new Date().toISOString().slice(0,10);status.textContent=kmText("saved");await loadCalendar()}catch(e){status.textContent=e.message}}
function prefPayload(){return {language:f$("prefLanguage").value,email_address:f$("emailAddress").value.trim()||null,email_enabled:f$("emailEnabled").checked,weather_alerts:f$("weatherAlerts").checked,crop_reminders:f$("cropReminders").checked,notification_consent:f$("notificationConsent").checked,latitude:window.kmLat??null,longitude:window.kmLon??null}}
async function loadPreferences(){try{const p=await farmApi("/api/preferences",{method:"GET",headers:{}});f$("prefLanguage").value=p.language||kmLanguage();f$("emailAddress").value=p.email_address||"";f$("emailEnabled").checked=p.email_enabled;f$("weatherAlerts").checked=p.weather_alerts;f$("cropReminders").checked=p.crop_reminders;f$("notificationConsent").checked=p.notification_consent;if(p.latitude!=null&&p.longitude!=null){window.kmLat=p.latitude;window.kmLon=p.longitude}}catch(e){f$("preferencesStatus").textContent=e.message}}
async function savePreferences(ev){ev.preventDefault();const status=f$("preferencesStatus");status.textContent=kmText("loading");try{const p=await farmApi("/api/preferences",{method:"PUT",body:JSON.stringify(prefPayload())});localStorage.setItem("km_language",p.language);f$("languageSelect")&&(f$("languageSelect").value=p.language);window.applyKMLanguage?.();status.textContent=kmText("saved")}catch(e){status.textContent=e.message}}
async function useWeatherLocation(){const status=f$("preferencesStatus");status.textContent=kmText("loading");if(!navigator.geolocation){status.textContent="This browser does not support location.";return}navigator.geolocation.getCurrentPosition(async pos=>{window.kmLat=pos.coords.latitude;window.kmLon=pos.coords.longitude;try{await farmApi("/api/preferences",{method:"PUT",body:JSON.stringify(prefPayload())});status.textContent="Location saved for forecast-based alerts."}catch(e){status.textContent=e.message}},err=>{status.textContent=err.code===1?"Location permission denied. Allow it in browser settings.":"Could not get location. Try again."},{enableHighAccuracy:false,timeout:12000,maximumAge:300000})}
async function testNotifications(){const status=f$("preferencesStatus"),out=f$("testResults");status.textContent=kmText("loading");out.classList.add("hidden");try{const d=await farmApi("/api/notifications/test",{method:"POST"});out.textContent=Object.entries(d.results||{}).map(([k,v])=>`${k}: ${v}`).join("\n")+"\n\n"+(d.note||"");out.classList.remove("hidden");status.textContent=kmText("testResult")}catch(e){status.textContent=e.message}}
document.addEventListener("DOMContentLoaded",()=>{if(!farmToken()){location.href="login.html";return}f$("eventDate").min=new Date().toISOString().slice(0,10);f$("chatForm").addEventListener("submit",sendChat);f$("calendarForm").addEventListener("submit",addCalendarEvent);f$("preferencesForm").addEventListener("submit",savePreferences);f$("setWeatherLocation").addEventListener("click",useWeatherLocation);f$("testNotifications").addEventListener("click",testNotifications);f$("prefLanguage").value=kmLanguage();loadCalendar();loadPreferences();document.addEventListener("km-language-changed",()=>{f$("prefLanguage").value=kmLanguage();loadCalendar()})});
