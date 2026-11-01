(() => {
  const API = 'http://127.0.0.1:8000';
  const token = () => localStorage.getItem('access_token') || localStorage.getItem('token');
  let activeConversation = null;
  let socket = null;
  let conversations = [];
  let notificationPermissionAsked = false;
  const $ = id => document.getElementById(id);
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(path, options={}) {
    const response = await fetch(API + path, { ...options, headers: { 'Content-Type':'application/json', Authorization:`Bearer ${token()}`, ...(options.headers||{}) }});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Chat request failed');
    return data;
  }
  function dateLabel(value) { if (!value) return ''; const d=new Date(value); return Number.isNaN(d.getTime())?'':d.toLocaleString([], {dateStyle:'short',timeStyle:'short'}); }
  function showStatus(message) { $('chatStatus').textContent = message || ''; }

  window.startListingChat = async listingId => {
    try {
      const result = await request(`/api/marketplace/listings/${listingId}/chat`, {method:'POST', body:'{}'});
      await loadConversations();
      await openConversation(result.conversation_id);
      $('chatStatus').textContent = 'Private conversation opened for this crop listing.';
      $('activeChatHeader').scrollIntoView({behavior:'auto',block:'nearest'});
    } catch (error) { alert(error.message); }
  };

  async function loadConversations() {
    try {
      const data = await request('/api/marketplace/chats'); conversations = data.conversations || [];
      const list = $('chatConversationList');
      if (!conversations.length) list.innerHTML='<p class="muted">No conversations yet. Start from a crop listing using “Chat with farmer”.</p>';
      else list.innerHTML=conversations.map(c=>`<button type="button" class="km-chat-conversation ${Number(c.conversation_id)===Number(activeConversation)?'active':''}" data-conversation="${c.conversation_id}"><span class="km-chat-person">${escapeHTML(c.other_name)}</span><span class="km-chat-crop">${escapeHTML(c.commodity)} · ${escapeHTML(c.state||'')}</span><span class="km-chat-preview">${escapeHTML(c.last_message||'No messages yet')}</span><span class="km-chat-meta">${dateLabel(c.last_message_at||c.updated_at)} ${Number(c.unread_count)>0?`<b class="km-unread-badge">${c.unread_count}</b>`:''}</span></button>`).join('');
      list.querySelectorAll('[data-conversation]').forEach(button=>button.addEventListener('click',()=>openConversation(Number(button.dataset.conversation))));
      const unread=conversations.reduce((sum,c)=>sum+Number(c.unread_count||0),0);
      $('chatUnreadBadge').hidden=unread===0; $('chatUnreadBadge').textContent=String(unread);
    } catch(error) { $('chatConversationList').innerHTML=`<p class="muted">${escapeHTML(error.message)}</p>`; }
  }

  async function openConversation(id) {
    activeConversation=id;
    const convo=conversations.find(c=>Number(c.conversation_id)===Number(id));
    $('activeChatHeader').innerHTML=convo?`<strong>${escapeHTML(convo.other_name)}</strong><span class="muted">${escapeHTML(convo.commodity)} · ${escapeHTML(convo.variety||'')} · ${escapeHTML(convo.district||'')}, ${escapeHTML(convo.state||'')}</span>`:'<strong>Conversation</strong>';
    $('chatMessageInput').disabled=false; $('sendChatMessage').disabled=false;
    try {
      const data=await request(`/api/marketplace/chats/${id}/messages`);
      renderMessages(data.messages||[]); await loadNotifications(); await loadConversations();
    } catch(error) { showStatus(error.message); }
  }
  function renderMessages(messages) {
    const box=$('chatMessages');
    if(!messages.length){box.innerHTML='<p class="muted">No messages yet. Say hello to discuss this crop.</p>';return;}
    box.innerHTML=messages.map(m=>`<article class="km-chat-bubble ${Number(m.sender_id)===currentUserId?'mine':'theirs'}"><div class="km-chat-message-text">${escapeHTML(m.message).replace(/\n/g,'<br>')}</div><small>${escapeHTML(m.sender_name)} · ${dateLabel(m.created_at)} ${Number(m.sender_id)===currentUserId?(m.is_read?'· Read':'· Sent'):''}</small></article>`).join('');
    box.scrollTop=box.scrollHeight;
  }
  let currentUserId=0;
  async function loadCurrentUser(){try{const me=await request('/api/auth/me');currentUserId=Number(me.id);}catch(_){}}

  async function loadNotifications() {
    try {
      const data=await request('/api/marketplace/chat-notifications');
      $('notificationCount').hidden=!data.unread_count; $('notificationCount').textContent=String(data.unread_count||0);
      const items=data.notifications||[];
      $('chatNotificationList').innerHTML=items.length?items.slice(0,8).map(n=>`<button type="button" class="km-notification-item ${n.is_read?'':'unread'}" data-open-chat="${n.conversation_id}"><strong>${escapeHTML(n.title)}</strong><span>${escapeHTML(n.body)}</span><small>${dateLabel(n.created_at)}</small></button>`).join(''):'<p class="muted">No notifications yet.</p>';
      $('chatNotificationList').querySelectorAll('[data-open-chat]').forEach(b=>b.addEventListener('click',()=>openConversation(Number(b.dataset.openChat))));
    } catch(error) { $('chatNotificationList').innerHTML=`<p class="muted">${escapeHTML(error.message)}</p>`; }
  }
  async function sendMessage(event) {
    event.preventDefault(); const input=$('chatMessageInput'), message=input.value.trim();
    if(!activeConversation||!message)return;
    $('sendChatMessage').disabled=true;
    try { await request(`/api/marketplace/chats/${activeConversation}/messages`,{method:'POST',body:JSON.stringify({message})}); input.value=''; await openConversation(activeConversation); showStatus('Message sent.'); }
    catch(error){showStatus(error.message);} finally {$('sendChatMessage').disabled=false;}
  }
  function connectSocket() {
    if(!token() || !('WebSocket' in window))return;
    const scheme=location.protocol==='https:'?'wss':'ws';
    socket=new WebSocket(`${scheme}://127.0.0.1:8000/ws/marketplace-chat?token=${encodeURIComponent(token())}`);
    socket.onmessage=async event=>{
      let payload; try{payload=JSON.parse(event.data)}catch(_){return;}
      if(payload.type!=='new_message')return;
      await loadConversations(); await loadNotifications();
      if(Number(payload.conversation_id)===Number(activeConversation)) await openConversation(activeConversation);
      if(Number(payload.message?.sender_id)!==currentUserId && 'Notification' in window && Notification.permission==='granted') {
        const n=new Notification('Kisan Mitra · New message',{body:payload.message?.message||'You received a new message.'});
        n.onclick=()=>{window.focus();openConversation(Number(payload.conversation_id));n.close();};
      }
    };
    socket.onclose=()=>{setTimeout(()=>{if(document.visibilityState!=='hidden')connectSocket();},5000);};
  }
  $('chatComposer').addEventListener('submit',sendMessage);
  $('refreshChats').addEventListener('click',async()=>{await loadConversations();await loadNotifications();if(activeConversation)await openConversation(activeConversation);});
  $('enableBrowserNotifications').addEventListener('click',async()=>{
    if(!('Notification' in window)){showStatus('This browser does not support desktop notifications. In-app notifications will still work.');return;}
    const permission=await Notification.requestPermission();
    showStatus(permission==='granted'?'Browser notifications enabled.':'Browser notifications were not enabled. In-app notifications remain available.');
  });
  document.addEventListener('km-role-ready',async()=>{
    await loadCurrentUser(); await loadConversations(); await loadNotifications(); connectSocket();
    // Poll as a fallback for browsers or networks where WebSocket is unavailable.
    setInterval(async()=>{await loadConversations();await loadNotifications();},20000);
  },{once:true});
})();
