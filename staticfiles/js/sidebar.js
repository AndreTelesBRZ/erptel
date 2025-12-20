(function () {
  let overlay = null;

  function updateOverlay() {
    if (!overlay) {
      return;
    }
    const isCollapsed = document.body.classList.contains('erp-sidebar-collapsed');
    const isMobile = window.matchMedia('(max-width: 1024px)').matches;
    overlay.style.display = !isCollapsed && isMobile ? 'block' : 'none';
  }

  function setSidebarCollapsed(collapsed, persist) {
    if (collapsed) {
      document.body.classList.add('erp-sidebar-collapsed');
    } else {
      document.body.classList.remove('erp-sidebar-collapsed');
    }
    if (persist) {
      try {
        localStorage.setItem('erpSidebarCollapsed', collapsed ? '1' : '0');
      } catch (error) {
        // Ignore storage errors (private mode, quota exceeded, etc.)
      }
    }
    updateOverlay();
  }

  window.toggleSidebar = function toggleSidebar() {
    const collapsed = document.body.classList.contains('erp-sidebar-collapsed');
    setSidebarCollapsed(!collapsed, true);
  };

  document.addEventListener('DOMContentLoaded', function () {
    overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.addEventListener('click', function () {
      setSidebarCollapsed(true, true);
    });
    document.body.appendChild(overlay);

    let collapsedPref = null;
    try {
      collapsedPref = localStorage.getItem('erpSidebarCollapsed');
    } catch (error) {
      collapsedPref = null;
    }

    if (collapsedPref === null) {
      setSidebarCollapsed(true, true);
    } else {
      setSidebarCollapsed(collapsedPref === '1', false);
    }
  });

  window.addEventListener('resize', updateOverlay);
})();
