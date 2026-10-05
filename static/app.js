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
