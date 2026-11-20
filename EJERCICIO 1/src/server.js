const app = require('./app');
const { port } = require('./config');

app.listen(port, () => console.log(`Servidor de correo en http://localhost:${port}`));