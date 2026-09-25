# Embedded chatbot styling

The website's `mountChainlitWidget` options must include:

```js
customCssUrl: "https://everydayai-production.up.railway.app/public/widget.css"
```

Add this property to the existing options; preserve the server URL, button settings,
and other website configuration. If the embed already uses a custom stylesheet,
merge the rules from `public/widget.css` into that stylesheet instead.

Copilot renders inside a shadow root. It loads `customCssUrl` from the website's
embed options, not the standalone chatbot's `[UI].custom_css` setting. Deploying
the stylesheet to Railway makes it available but does not update the website's
embed options automatically.

The stylesheet reduces the header logo image from 100px to 48px, and changes
header padding from 16px on the top and sides to 8px vertically and 12px
horizontally. The SVG's transparent margins make the visible mark about 24px.
Message avatars and the launcher button are outside these selectors.
