(function () {
  const THEME_KEY = 'weldsight-theme';
  const storedTheme = localStorage.getItem(THEME_KEY);
  const requestedTheme = new URLSearchParams(location.search).get('theme');
  document.documentElement.dataset.theme = ['light', 'dark'].includes(requestedTheme)
    ? requestedTheme
    : (storedTheme || 'light');

  const icons = {
    home: '<svg viewBox="0 0 24 24"><path d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>',
    image: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 3-3 5 5"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 9 5 3-5 3zM7 4v16M17 4v16"/></svg>',
    camera: '<svg viewBox="0 0 24 24"><path d="M5 8h3l1.5-2h5L16 8h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z"/><circle cx="12" cy="14" r="3.5"/></svg>',
    sun: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"/></svg>',
    moon: '<svg viewBox="0 0 24 24"><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5z"/></svg>'
  };

  function currentPage() {
    const path = location.pathname;
    if (path.endsWith('/img.html')) return 'image';
    if (path.endsWith('/vid.html')) return 'video';
    if (path.endsWith('/cam.html')) return 'camera';
    return 'home';
  }

  function navLink(key, href, label) {
    return `<a class="app-nav-link${currentPage() === key ? ' active' : ''}" href="${href}">${icons[key]}<span>${label}</span></a>`;
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
    const toggle = document.querySelector('.theme-toggle');
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(theme === 'dark'));
      toggle.setAttribute('aria-label', theme === 'dark' ? '切换到浅色主题' : '切换到深色主题');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const children = Array.from(document.body.childNodes).filter(node =>
      node.nodeType !== Node.ELEMENT_NODE || !['SCRIPT', 'AUDIO'].includes(node.tagName)
    );
    const main = document.createElement('main');
    main.className = `app-main page-${currentPage()}`;
    children.forEach(node => main.appendChild(node));

    if (currentPage() === 'home') {
      const descriptions = [
        ['图片检测', '上传焊缝图片，快速识别缺陷位置'],
        ['视频检测', '逐帧分析视频并生成检测结果'],
        ['实时检测', '连接摄像头，持续监测焊缝状态'],
      ];
      main.querySelectorAll('ul a').forEach((link, index) => {
        const content = descriptions[index];
        if (content) {
          link.innerHTML = `<span><strong>${content[0]}</strong><small>${content[1]}</small></span><b aria-hidden="true">›</b>`;
        }
      });
    }

    const shell = document.createElement('div');
    shell.className = 'app-shell';
    shell.innerHTML = `
      <header class="app-header">
        <a class="brand" href="index.html" aria-label="WeldSight 首页"><span class="brand-mark">W</span><strong>WeldSight</strong><span class="brand-subtitle">焊缝缺陷智能检测</span></a>
        <div class="header-actions"><span class="service-state"><i></i>系统在线</span><button class="theme-toggle" type="button"><span>${icons.sun}</span><i></i><span>${icons.moon}</span></button></div>
      </header>
      <aside class="app-sidebar"><nav aria-label="主要导航">
        ${navLink('home', 'index.html', '首页概览')}
        ${navLink('image', 'img.html', '图片检测')}
        ${navLink('video', 'vid.html', '视频检测')}
        ${navLink('camera', 'cam.html', '实时检测')}
      </nav><p class="sidebar-foot">YOLO 焊缝评片系统</p></aside>`;
    shell.appendChild(main);
    document.body.prepend(shell);

    const toggle = document.querySelector('.theme-toggle');
    toggle.addEventListener('click', () => {
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });
    applyTheme(document.documentElement.dataset.theme);
  });
})();
