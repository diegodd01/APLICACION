const path = require('path');
const express = require('express');
const mailRoutes = require('./routes/mail.routes');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));
app.use('/api', mailRoutes);

module.exports = app;