import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'inputError',
  standalone: false,
})
export class InputErrorPipe implements PipeTransform {

  transform(value: string): string {
    let rvalue: string = '';
    if (value !== null){
      switch(value){
        case 'login':
          rvalue = "Aucun utilisateur n'a été trouvé avec ce login pour cette application"
          break;
        case 'password':
          rvalue = "Mot de passe invalide"
          break;
        case 'bug':
          rvalue = "Une erreur inconnue est survenue durant le login"
          break;
        default:
          rvalue = "Une erreur inconnue est survenue durant le login"

      }
    }
    return rvalue;
  }

}
