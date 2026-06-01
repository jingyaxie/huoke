(() => {
  const define = (object, key, value) => {
    try {
      Object.defineProperty(object, key, { get: () => value, configurable: true });
    } catch (_) {}
  };

  // navigator.webdriver
  define(navigator, "webdriver", undefined);
  delete Object.getPrototypeOf(navigator).webdriver;

  // window.chrome
  if (!window.chrome) {
    window.chrome = {};
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = {
      connect: () => {},
      sendMessage: () => {},
      onMessage: { addListener: () => {}, removeListener: () => {} },
    };
  }

  // languages / platform
  define(navigator, "languages", ["zh-CN", "zh", "en-US", "en"]);
  define(navigator, "language", "zh-CN");
  define(navigator, "platform", "MacIntel");
  define(navigator, "hardwareConcurrency", 8);
  define(navigator, "deviceMemory", 8);
  define(navigator, "maxTouchPoints", 0);

  // plugins / mimeTypes length (headless often returns 0)
  const fakePlugins = [{ name: "Chrome PDF Plugin" }, { name: "Chrome PDF Viewer" }, { name: "Native Client" }];
  define(navigator, "plugins", fakePlugins);
  define(navigator, "mimeTypes", [{ type: "application/pdf" }]);

  // permissions.query for notifications
  if (navigator.permissions && navigator.permissions.query) {
    const originalQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (parameters) => {
      if (parameters && parameters.name === "notifications") {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return originalQuery(parameters);
    };
  }

  // iframe contentWindow
  try {
    const elementDescriptor = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "contentWindow");
    if (elementDescriptor && elementDescriptor.get) {
      Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
        get: function () {
          const win = elementDescriptor.get.call(this);
          if (win) {
            try {
              define(win.navigator, "webdriver", undefined);
            } catch (_) {}
          }
          return win;
        },
      });
    }
  } catch (_) {}

  // WebGL vendor / renderer
  const patchWebGL = (contextPrototype) => {
    if (!contextPrototype || !contextPrototype.getParameter) return;
    const getParameter = contextPrototype.getParameter;
    contextPrototype.getParameter = function (parameter) {
      if (parameter === 37445) return "Intel Inc.";
      if (parameter === 37446) return "Intel Iris OpenGL Engine";
      return getParameter.call(this, parameter);
    };
  };
  try {
    patchWebGL(WebGLRenderingContext && WebGLRenderingContext.prototype);
    patchWebGL(WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  } catch (_) {}

  // outer/inner dimensions sanity
  if (window.outerWidth === 0 && window.innerWidth > 0) {
    define(window, "outerWidth", window.innerWidth);
    define(window, "outerHeight", window.innerHeight + 88);
  }
})();
