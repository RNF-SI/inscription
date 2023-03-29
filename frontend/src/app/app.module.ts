import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { SignUpComponent } from './sign-up/sign-up.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip'
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import {MatCardModule} from '@angular/material/card';
import {MatGridListModule} from '@angular/material/grid-list';
import { MatInputModule } from  '@angular/material/input';
import { MatSelectModule } from  '@angular/material/select';
import { NgxMatSelectSearchModule } from 'ngx-mat-select-search';


import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { HttpClientModule } from '@angular/common/http';
import { ToastrModule } from 'ngx-toastr';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { RouterModule } from '@angular/router';
import { HomeComponent } from './home/home.component';
import { FontAwesomeModule, FaIconLibrary } from '@fortawesome/angular-fontawesome';
import { RandomOrderPipe } from './pipes/random-order.pipe';

import { faKey, faUserPlus, faArrowUpRightFromSquare } from '@fortawesome/free-solid-svg-icons';
import { faFacebook, faInstagram, faGithub, faLinkedin} from '@fortawesome/free-brands-svg-icons';
import { SearchPipe } from './search.pipe';
import { MatButtonModule } from '@angular/material/button';

@NgModule({
  declarations: [
    AppComponent,
    SignUpComponent,
    HomeComponent,
    RandomOrderPipe,
    SearchPipe
  ],
  imports: [
    HttpClientModule,
    BrowserModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    MatDividerModule,
    MatIconModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatCardModule,
    MatGridListModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    NgxMatSelectSearchModule,
    FormsModule,
    ReactiveFormsModule,
    ToastrModule.forRoot({
      timeOut:15000
    }),
    NgbModule,
    RouterModule,
    FontAwesomeModule
  ],
  providers: [],
  bootstrap: [AppComponent]
})
export class AppModule {
  constructor(library: FaIconLibrary) {
    library.addIcons(
      faKey,
      faUserPlus,
      faArrowUpRightFromSquare,
      faFacebook,
      faInstagram,
      faGithub,
      faLinkedin
    );
  }
 }
