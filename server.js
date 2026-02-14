const express = require('express');
const http = require('http');
const mongoose = require('mongoose');
const { Server } = require('socket.io');
const session = require('express-session');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// إعدادات EJS (بما أن الملفات في الجذر)
app.set('view engine', 'ejs');
app.set('views', __dirname);
app.use(express.urlencoded({ extended: true }));
app.use(session({ secret: process.env.SESSION_SECRET || 'secret-key', resave: false, saveUninitialized: true }));

// الاتصال بـ MongoDB
mongoose.connect(process.env.MONGODB_URL)
  .then(() => console.log("Connected to MongoDB Atlas"))
  .catch(err => console.error(err));

// تعريف المستخدم (User Schema)
const userSchema = new mongoose.Schema({
    username: String,
    isAdmin: { type: Boolean, default: false },
    isApproved: { type: Boolean, default: false } // التحكم في الدخول
});
const User = mongoose.model('User', userSchema);

// المسارات (Routes)
app.get('/', (req, res) => res.render('login'));

app.get('/chat', async (req, res) => {
    // هنا نتأكد إذا كان المستخدم مسموح له بالدردشة
    const user = await User.findOne({ username: req.session.username });
    if (user && user.isApproved) {
        res.render('index', { user });
    } else {
        res.render('blocked');
    }
});

app.get('/admin', async (req, res) => {
    const users = await User.find();
    res.render('admin', { users });
});

// تفعيل المستخدم من لوحة التحكم
app.post('/approve/:id', async (req, res) => {
    await User.findByIdAndUpdate(req.params.id, { isApproved: true });
    res.redirect('/admin');
});

// Socket.io للتواصل الفوري
io.on('connection', (socket) => {
    socket.on('chat message', (msg) => {
        io.emit('chat message', msg);
    });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`Server running on port ${PORT}`));
