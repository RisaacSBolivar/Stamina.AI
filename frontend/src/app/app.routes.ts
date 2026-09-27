import { Routes } from '@angular/router';

import { puedeSalir } from './core/salida.guard';

/**
 * Tres rutas: la portada, la página guiada y el panel de «por qué esta
 * estrategia».
 *
 * La portada tiene ruta propia y no es un interruptor dentro del armazón para
 * que recargar la página o entrar por un enlace directo se comporten igual: la
 * cabecera se decide mirando la URL, no una bandera en memoria.
 *
 * Todas con carga diferida, para que el bundle inicial no arrastre ECharts si
 * el usuario todavía no ha calculado nada.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'bienvenida' },
  {
    path: 'bienvenida',
    title: 'Stamina.AI — estrategia de ritmo para tu carrera',
    loadComponent: () => import('./pages/bienvenida/bienvenida.page').then((m) => m.BienvenidaPage),
  },
  {
    path: 'estrategia',
    title: 'Stamina.AI — tu estrategia de ritmo',
    loadComponent: () => import('./pages/estrategia/estrategia.page').then((m) => m.EstrategiaPage),
    canDeactivate: [puedeSalir],
  },
  {
    path: 'detalle',
    title: 'Stamina.AI — por qué esta estrategia',
    loadComponent: () => import('./pages/detalle/detalle.page').then((m) => m.DetallePage),
    // También aquí: el botón de salir vive en la cabecera y se ve desde las dos.
    canDeactivate: [puedeSalir],
  },
  { path: '**', redirectTo: 'bienvenida' },
];
