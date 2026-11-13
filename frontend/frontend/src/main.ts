import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

// Kiosk: no zoom from a touchpad pinch (Ctrl + wheel) or Safari gestures; touch pinch is off in styles.css.
document.addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
document.addEventListener('gesturestart', (e) => e.preventDefault());
// Kiosk: no menu from a long press (or a right click).
document.addEventListener('contextmenu', (e) => e.preventDefault());

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));
