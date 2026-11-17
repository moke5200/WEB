/* daily_ui.js —— 每日页统一交互（升级/降低 + 备注 + 存服务器）
 *
 * 规则（野哥 11-17 定）：
 *   · 每条内容都带 ↑提升 / ↓降低 两个标签
 *   · 点哪个，哪个旁边才出现文字输入框；不点就没有输入框
 *   · 两个都没点 = 优先级不变
 *   · 再点一次同一个标签 = 取消，框收起来
 *   · 标注实时回传服务器（以后不用复制粘贴），同时存 localStorage 兜底
 *
 * 用法：元素上带 data-id，页面里放一个引用 daily_ui.js 的 script 标签（上传时内联）
 */
(function () {
  var DAY = window.__DAILY_DAY__ || '';
  var NS = 'wool-' + DAY + '-';
  var API = '/api/feedback';

  function load(id) {
    try { return JSON.parse(localStorage.getItem(NS + id) || '{}'); }
    catch (e) { return {}; }
  }
  function saveLocal(id, obj) {
    try { localStorage.setItem(NS + id, JSON.stringify(obj)); } catch (e) {}
  }
  function pushServer(id, obj) {
    if (!API) return;
    try {
      fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: id,
          day: DAY,
          pri: obj.pri || null,
          note: obj.note || null
        })
      }).catch(function () {});
    } catch (e) {}
  }

  function applyState(el, st) {
    var ta = el.querySelector('textarea.why');
    var up = el.querySelector('.btn.up');
    var dn = el.querySelector('.btn.down');
    if (up) up.classList.toggle('on', st.pri === 'up');
    if (dn) dn.classList.toggle('on', st.pri === 'down');
    if (ta) {
      ta.value = st.note || '';
      // 只有定了优先级才显示输入框；两个都没点 = 不变 = 不显示
      ta.style.display = st.pri ? '' : 'none';
    }
    if (st.pri) { el.dataset.pri = st.pri; } else { delete el.dataset.pri; }
  }

  function setPri(el, id, pri) {
    var st = load(id);
    if (st.pri === pri) {
      delete st.pri;           // 再点一次 = 取消
    } else {
      st.pri = pri;
    }
    saveLocal(id, st);
    pushServer(id, st);
    applyState(el, st);
    if (window.__dailyRefresh) window.__dailyRefresh();
  }

  function setNote(el, id, note) {
    var st = load(id);
    st.note = note;
    saveLocal(id, st);
    pushServer(id, st);
  }

  function mount(el) {
    var id = el.dataset.id;
    if (!id) return;
    applyState(el, load(id));

    el.querySelectorAll('.btn[data-p]').forEach(function (b) {
      b.addEventListener('click', function () {
        setPri(el, id, b.dataset.p);
      });
    });

    var ta = el.querySelector('textarea.why');
    if (ta) {
      var timer;
      ta.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { setNote(el, id, ta.value); }, 350);
      });
      // 备注框里的回车不提交表单
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ta.blur(); }
      });
    }
  }

  // 给没有 .act 的卡片补上按钮 + 输入框
  function ensureControls(el) {
    if (el.querySelector('.btn[data-p]')) return;
    var bar = document.createElement('div');
    bar.className = 'act';
    bar.innerHTML = '<button class="btn up" data-p="up">↑ 提升</button>' +
                    '<button class="btn down" data-p="down">↓ 降低</button>';
    var ta = document.createElement('textarea');
    ta.className = 'why';
    ta.placeholder = '为什么？（比如「这个我明天就想试」）';
    ta.style.display = 'none';
    el.appendChild(bar);
    el.appendChild(ta);
  }

  function init() {
    var items = [].slice.call(document.querySelectorAll('[data-id]'));
    items.forEach(function (el) {
      if (!el.classList.contains('item') && !el.classList.contains('card')) return;
      ensureControls(el);
      mount(el);
    });

    // 从服务器拉当天已有的标注（换浏览器/清缓存也能看到自己的标记）
    if (API && DAY) {
      try {
        fetch(API + '?day=' + encodeURIComponent(DAY), { headers: { 'Accept': 'application/json' } })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            (d.items || []).forEach(function (fb) {
              var el = document.querySelector('[data-id="' + fb.item_id + '"]');
              if (!el) return;
              var st = load(fb.item_id);
              if (fb.pri) st.pri = fb.pri;
              if (fb.note) st.note = fb.note;
              saveLocal(fb.item_id, st);
              applyState(el, st);
            });
          })
          .catch(function () {});
      } catch (e) {}
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
