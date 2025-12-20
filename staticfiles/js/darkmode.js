// Toggle dark mode by adding/removing `dark` class on <body>
(function(){
  const key = 'site:darkmode';
  function apply(value){
    if(value) document.body.classList.add('dark');
    else document.body.classList.remove('dark');
  }
  // read stored preference
  const stored = localStorage.getItem(key);
  if(stored !== null){
    apply(stored === '1');
  } else {
    // default: respect prefers-color-scheme
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    apply(prefersDark);
  }
  // helper to update button icon and aria state
  function updateButton(btn, isDark){
    if(!btn) return;
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    const icon = btn.querySelector('.dm-icon');
    if(icon){
      icon.innerHTML = isDark ? (btn.dataset.iconMoon || '') : (btn.dataset.iconSun || '');
      // add a short animation class
      icon.classList.add('toggling');
      setTimeout(()=> icon.classList.remove('toggling'), 360);
    }
  }

  // initialize button icon if present
  const defaultBtn = document.getElementById('dark-toggle');
  if(defaultBtn){
    const isDarkNow = document.body.classList.contains('dark');
    // ensure data attributes available: data-icon-sun / data-icon-moon
    updateButton(defaultBtn, isDarkNow);
  }

  // expose toggle on window for onclick binding; accepts optional button id to update icon/aria
  window.toggleDarkMode = function(buttonId){
    const isDark = document.body.classList.toggle('dark');
    localStorage.setItem(key, isDark ? '1' : '0');
    try{
      if(buttonId){
        const btn = document.getElementById(buttonId);
        updateButton(btn, isDark);
      }
    }catch(e){
      // ignore icon updates
    }
  };
})();
