import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { provideRouter, withComponentInputBinding, withRouterConfig } from '@angular/router';
import { provideEchartsCore } from 'ngx-echarts';

import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(
      routes,
      withComponentInputBinding(),
      // Al cancelar la salida con la flecha atras, el router tiene que devolver
      // la URL a su sitio. Con el modo por defecto («replace») lo hace pisando
      // la entrada actual, y queda una duplicada: la siguiente flecha atras se
      // consume sin ir a ninguna parte. «computed» recoloca la posicion real del
      // historial, asi que cancelar y volver a intentarlo pregunta otra vez.
      withRouterConfig({ canceledNavigationResolution: 'computed' }),
    ),
    provideHttpClient(withFetch()),
    // ECharts se carga bajo demanda: son ~1 MB que no hacen falta hasta que
    // hay una estrategia que dibujar.
    provideEchartsCore({ echarts: () => import('echarts') }),
  ],
};
