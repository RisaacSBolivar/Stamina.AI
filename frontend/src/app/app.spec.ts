import { Component, provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter, type Routes } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { App } from './app';
import { SesionService } from './core/sesion.service';

/** Una página de mentira: aquí se prueba el armazón, no lo que va dentro. */
@Component({ selector: 'app-vacio', template: '' })
class Vacio {}

/**
 * Rutas de mentira, por lo mismo: con las de verdad cada test arrastraría la
 * página guiada entera y sus llamadas a la API.
 */
const rutas: Routes = [
  { path: 'bienvenida', component: Vacio },
  { path: 'estrategia', component: Vacio },
];

describe('App', () => {
  beforeEach(async () => {
    // El nombre vive en `sessionStorage`, que sobrevive de un test al siguiente.
    sessionStorage.clear();

    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideZonelessChangeDetection(),
        provideRouter(rutas),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();
  });

  /** La cabecera depende de la URL, así que se navega antes de montar. */
  async function montarEn(url: string): Promise<ComponentFixture<App>> {
    await TestBed.inject(Router).navigateByUrl(url);
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    return fixture;
  }

  const textoDe = (fixture: ComponentFixture<App>): string =>
    (fixture.nativeElement as HTMLElement).textContent ?? '';

  it('monta el armazón de la aplicación', async () => {
    const fixture = await montarEn('/estrategia');
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('muestra la marca en la cabecera', async () => {
    const fixture = await montarEn('/estrategia');
    expect(textoDe(fixture)).toContain('Stamina');
  });

  it('incluye el descargo: no es consejo médico', async () => {
    const fixture = await montarEn('/estrategia');

    // No es decorativo: el producto prescribe esfuerzo físico y el descargo
    // tiene que estar siempre visible, no solo cuando hay estrategia.
    expect(textoDe(fixture)).toContain('No es consejo médico');
  });

  it('saluda por su nombre a quien se presentó en la portada', async () => {
    TestBed.inject(SesionService).presentarse('  Isaac  ');
    const fixture = await montarEn('/estrategia');

    expect(textoDe(fixture)).toContain('Isaac');
  });

  it('deja la portada sin cabecera ni pie, porque se presenta sola', async () => {
    const fixture = await montarEn('/bienvenida');
    const raiz = fixture.nativeElement as HTMLElement;

    expect(raiz.querySelector('header')).toBeNull();
    expect(raiz.querySelector('footer')).toBeNull();
  });
});
