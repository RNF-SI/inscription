import { ComponentFixture, TestBed } from '@angular/core/testing';

import { UpdatemoncompteComponent } from './updatemoncompte.component';

describe('UpdatemoncompteComponent', () => {
  let component: UpdatemoncompteComponent;
  let fixture: ComponentFixture<UpdatemoncompteComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ UpdatemoncompteComponent ]
    })
    .compileComponents();

    fixture = TestBed.createComponent(UpdatemoncompteComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
