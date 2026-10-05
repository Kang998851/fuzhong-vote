// 附中墙 · 前端小脚本：移动端菜单、倒计时、照片预览
(function () {
  // 移动端边栏开关
  var btn = document.getElementById('hamburger');
  var scrim = document.getElementById('scrim');
  if (btn) btn.addEventListener('click', function () {
    document.body.classList.toggle('nav-open');
  });
  if (scrim) scrim.addEventListener('click', function () {
    document.body.classList.remove('nav-open');
  });

  // 倒计时（data-deadline 为 ISO 时间）
  function tick() {
    document.querySelectorAll('.countdown[data-deadline]').forEach(function (el) {
      var end = new Date(el.getAttribute('data-deadline')).getTime();
      var diff = end - Date.now();
      if (diff <= 0) {
        el.innerHTML = '投票已截止';
        return;
      }
      var d = Math.floor(diff / 864e5);
      var h = Math.floor(diff % 864e5 / 36e5);
      el.innerHTML = '距离截止还有 <b>' + d + '</b> 天 <b>' + h + '</b> 小时';
    });
  }
  tick();
  setInterval(tick, 60000);

  // 报名照片预览 + 拖拽上传
  var input = document.getElementById('photo-input');
  var preview = document.getElementById('photo-preview');
  var zone = document.getElementById('photo-dropzone');
  function handlePhotoFile(f) {
    if (!f) { preview.style.display = 'none'; return; }
    if (f.type && f.type.indexOf('image/') !== 0) {
      alert('请上传 JPG / PNG / WebP 格式的图片');
      input.value = '';
      preview.style.display = 'none';
      return;
    }
    if (f.size > 4 * 1024 * 1024) {
      alert('照片不能超过 4MB');
      input.value = '';
      preview.style.display = 'none';
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      preview.src = e.target.result;
      preview.style.display = 'block';
    };
    reader.readAsDataURL(f);
  }
  if (input && preview) {
    input.addEventListener('change', function () {
      handlePhotoFile(input.files[0]);
    });
  }
  if (zone && input) {
    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        zone.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        zone.classList.remove('dragover');
      });
    });
    zone.addEventListener('drop', function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      var dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      handlePhotoFile(f);
    });
  }
})();

// 点赞 / 投票：无刷新提交 + Apple 风格动效
(function () {
  function restart(el, cls) {
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
  }

  // 数字平滑滚动（easeOutExpo）
  function animateCount(el, to) {
    var from = parseInt(el.textContent, 10) || 0;
    to = parseInt(to, 10) || 0;
    if (from === to) { restart(el, 'bump'); return; }
    var dur = 500, start = null;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / dur);
      var eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      el.textContent = Math.round(from + (to - from) * eased);
      if (p < 1) requestAnimationFrame(step);
      else restart(el, 'bump');
    }
    requestAnimationFrame(step);
  }

  // 点按时的扩散圆环（触感反馈的视觉版）
  function tapRing(el, green) {
    var s = document.createElement('span');
    s.className = 'tap-ring' + (green ? ' green' : '');
    el.appendChild(s);
    setTimeout(function () { s.remove(); }, 750);
  }

  // 投票成功撒花：纸片上扬后受重力下落
  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function confetti(container) {
    if (reduceMotion || !container.animate) return;
    var colors = ['#e14b5a', '#f5b301', '#3fa7ff', '#3fae6a', '#b678ff', '#ff8c42'];
    for (var i = 0; i < 24; i++) {
      (function (i) {
        var s = document.createElement('span');
        s.className = 'confetti-bit';
        var w = 5 + Math.random() * 6;
        s.style.width = w + 'px';
        s.style.height = (w * (0.6 + Math.random() * 0.9)) + 'px';
        s.style.background = colors[i % colors.length];
        if (Math.random() < 0.3) s.style.borderRadius = '50%';
        container.appendChild(s);
        var angle = Math.random() * Math.PI * 2;
        var dist = 60 + Math.random() * 100;
        var dx = Math.cos(angle) * dist;
        var dy = Math.sin(angle) * dist * 0.55 - 46;
        var rot = Math.round(Math.random() * 720 - 360) + 'deg';
        var anim = s.animate([
          { transform: 'translate(-50%,-50%) rotate(0deg)', opacity: 1 },
          { transform: 'translate(calc(-50% + ' + Math.round(dx * 0.7) + 'px), calc(-50% + ' + Math.round(dy * 0.7) + 'px)) rotate(' + rot + ')',
            opacity: 1, offset: 0.55 },
          { transform: 'translate(calc(-50% + ' + Math.round(dx) + 'px), calc(-50% + ' + Math.round(dy + 110) + 'px)) rotate(' + rot + ')',
            opacity: 0 }
        ], { duration: 950 + Math.random() * 550, easing: 'cubic-bezier(.2,.7,.3,1)' });
        anim.onfinish = function () { s.remove(); };
      })(i);
    }
  }

  // 通用：拦截表单走 fetch，失败时降级为整页提交
  function ajaxify(form, onOk) {
    if (form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (form.dataset.busy) return;
      form.dataset.busy = '1';
      fetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form),
        credentials: 'same-origin'
      }).then(function (r) { return r.json(); })
        .then(function (data) {
          delete form.dataset.busy;
          if (data && data.ok) onOk(data);
          else alert((data && data.error) || '操作失败，请重试');
        })
        .catch(function () { form.submit(); });
    });
  }

  // 点赞：爱心弹簧 pop + 圆环扩散 + 数字滚动
  document.querySelectorAll('form.js-like').forEach(function (form) {
    ajaxify(form, function (data) {
      var btn = form.querySelector('.js-like-btn');
      var heart = btn.querySelector('.heart');
      var count = btn.querySelector('.like-count');
      heart.textContent = data.liked ? '♥' : '♡';
      btn.classList.toggle('is-liked', data.liked);
      if (data.liked) {
        restart(btn, 'pop');
        tapRing(btn, false);
      }
      animateCount(count, data.likes);
    });
  });

  // 投票：卡片轻沉回弹 + 绿色圆环 + 票数滚动
  function paintVoteState(list, votedCid) {
    var castUrl = list.dataset.castUrl, csrf = list.dataset.csrf;
    list.querySelectorAll('[data-cid]').forEach(function (item) {
      var box = item.querySelector('[data-actions]');
      if (!box) return;
      if (item.dataset.cid === String(votedCid)) {
        box.innerHTML = '<button class="btn btn-sm" disabled>已投票 ✓</button>';
      } else {
        box.innerHTML =
          '<form action="' + castUrl + '" method="post" class="inline-form js-vote" data-cid="' + item.dataset.cid + '">' +
          '<input type="hidden" name="csrf_token" value="' + csrf + '">' +
          '<input type="hidden" name="candidate_id" value="' + item.dataset.cid + '">' +
          '<button class="btn btn-primary btn-sm" type="submit">改投TA</button></form>';
      }
    });
    list.querySelectorAll('form.js-vote').forEach(bindVote);
  }

  function bindVote(form) {
    ajaxify(form, function (data) {
      var list = form.closest('[data-vote-list]');
      paintVoteState(list, data.candidate_id);
      var item = list.querySelector('[data-cid="' + data.candidate_id + '"]');
      if (item) {
        var num = item.querySelector('.vote-num');
        if (num) animateCount(num, data.votes);
        restart(item, 'vote-flash');
        confetti(item);
      }
    });
  }
  document.querySelectorAll('form.js-vote').forEach(bindVote);

  // 公告投票：点选项即投，可改投
  function paintPoll(poll, data) {
    var byId = {};
    data.options.forEach(function (o) { byId[o.id] = o; });
    poll.querySelectorAll('form.js-poll-opt').forEach(function (form) {
      var o = byId[parseInt(form.dataset.oid, 10)];
      if (!o) return;
      var btn = form.querySelector('.poll-opt');
      var mine = data.option_id === o.id;
      btn.classList.toggle('mine', mine);
      if (mine) {
        btn.setAttribute('disabled', '');
        tapRing(btn, true);
      } else {
        btn.removeAttribute('disabled');
      }
      btn.querySelector('.poll-fill').style.width = o.pct + '%';
      var num = btn.querySelector('.vote-num');
      if (num) animateCount(num, o.votes);
      var pct = btn.querySelector('.poll-pct');
      if (pct) pct.textContent = o.pct;
    });
    var foot = poll.querySelector('[data-foot]');
    if (foot) foot.textContent = data.total + ' 人参与 · 你已投票，可改投';
  }
  document.querySelectorAll('form.js-poll-opt').forEach(function (form) {
    ajaxify(form, function (data) {
      paintPoll(form.closest('[data-poll]'), data);
    });
  });
})();
