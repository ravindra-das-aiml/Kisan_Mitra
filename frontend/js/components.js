async function loadComponent(id,file){
 const e=document.getElementById(id); if(!e)return;
 try{
  const r=await fetch(file); if(!r.ok)throw Error("component not found");
  e.innerHTML=await r.text();
  if(id==="header"){
   const b=e.querySelector("#logoutBtn");
   b?.addEventListener("click",()=>{["access_token","token"].forEach(k=>localStorage.removeItem(k));location.replace("landing.html")});
   const theme=e.querySelector("#themeBtn");
   theme?.addEventListener("click",toggleTheme);
   updateThemeButton();
   applyActiveNavigation(e);
   document.dispatchEvent(new CustomEvent("km-header-ready"));
   const lang=e.querySelector("#languageSelect");
   if(lang){lang.value=window.kmLanguage?.()||"en";lang.addEventListener("change",()=>{localStorage.setItem("km_language",lang.value);window.applyKMLanguage?.();document.dispatchEvent(new CustomEvent("km-language-changed",{detail:{language:lang.value}}));});}
   window.applyKMLanguage?.();
   applyRoleNavigation();
  }
 }catch(x){console.error(x)}
}
function updateThemeButton(){
 const button=document.getElementById("themeBtn");
 if(!button)return;
 const isDark=document.documentElement.dataset.theme!=="light";
 const icon=button.querySelector(".km-mode-icon");
 const label=button.querySelector(".km-mode-label");
 if(icon)icon.textContent=isDark?"☼":"☾";
 if(label)label.textContent="Dark/Light Mode";
 button.setAttribute("aria-label",isDark?"Switch to light mode":"Switch to dark mode");
 button.setAttribute("aria-pressed",String(!isDark));
}
function applyTheme(){const t=localStorage.getItem("km_theme")||"dark";document.documentElement.dataset.theme=t;updateThemeButton()}
function toggleTheme(){const t=document.documentElement.dataset.theme==="dark"?"light":"dark";localStorage.setItem("km_theme",t);applyTheme();document.dispatchEvent(new CustomEvent("km-theme-changed",{detail:{theme:t}}))}
function applyActiveNavigation(headerRoot=document){
 const page=location.pathname.split("/").pop()||"index.html";
 const activePage=page==="report.html"?"reports.html":page;
 document.body.dataset.kmPage=page;
 headerRoot.querySelectorAll?.("nav a[href]").forEach(link=>{
  let target="";
  try{target=new URL(link.getAttribute("href"),location.href).pathname.split("/").pop()||"index.html"}catch(_){return}
  const active=target===activePage;
  link.classList.toggle("km-nav-active",active);
  if(active)link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");
 });
}
applyTheme();
document.addEventListener("DOMContentLoaded",()=>{loadComponent("header","header.html");loadComponent("footer","footer.html");window.applyKMLanguage?.();});

async function applyRoleNavigation(){
 const token=localStorage.getItem("access_token");
 const path=location.pathname.split("/").pop();
 const publicPages=["login.html","register.html",""];
 if(!token){ if(!publicPages.includes(path)){location.href="login.html";} return; }
 try{
  const r=await fetch("http://localhost:8000/api/auth/me",{headers:{Authorization:"Bearer "+token}});
  if(!r.ok)throw Error("Session expired");
  const user=await r.json(); const role=user.role;
  document.querySelectorAll("[data-roles]").forEach(el=>{
   const allowed=(el.dataset.roles||"").split(","); el.hidden=!allowed.includes(role);
  });
  const access={
   "index.html":["farmer","admin"],"farm-tools.html":["farmer","admin"],
   "reports.html":["farmer","admin"],"admin.html":["admin"]
  };
  if(access[path]&&!access[path].includes(role)){
   location.replace(role==="buyer"?"marketplace.html":role==="admin"?"admin.html":"index.html");return;
  }
  document.documentElement.dataset.userRole=role;
  document.dispatchEvent(new CustomEvent("km-role-ready",{detail:{role,user}}));
 }catch(e){localStorage.removeItem("access_token");location.href="login.html";}
}
