const express = require('express');
const http = require('http');
const mongoose = require('mongoose');
const { Server } = require('socket.io');
const session = require('express-session');
const crypto = require('crypto');
const cloudinary = require('cloudinary').v2;
const { CloudinaryStorage } = require('multer-storage-cloudinary');
const multer = require('multer');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// إعدادات Cloudinary (تأكد من وضع القيم في Render)
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET
});

const storage = new CloudinaryStorage({
  cloudinary: cloudinary,
  params: { folder: 'chat_images', allowed_formats: ['jpg', 'png'] },
});
const upload = multer({ storage: storage });

// الإعدادات العامة
app.set('view engine', 'ejs');
app.set('views', __dirname);
app.use(express.urlencoded({ extended: true }));
app.use(session({ secret: process.env.SESSION_SECRET || 'secret', resave: false, saveUninitialized: true }));

// الاتصال بـ MongoDB
mongoose.connect(process.env.MONGODB_URL).catch(err => console.log(err));

// النماذج (Models)
const User = mongoose.model('User', { username: String, isAdmin: { type: Boolean, default: false } });
const Invite = mongoose.model('Invite', { code: String, used: { type: Boolean, default: false } });

// المسارات (Routes)
app.get('/', (req, res) => res.render('login'));

app.post('/login', async (req, res) => {
    const { username } = req.body;
    let user = await User.findOne({ username });
    if (!user) user = await User.create({ username });
    req.session.user = user;
    res.redirect('/chat');
});

app.get('/chat', async (req, res) => {
    if (!req.session.user) return res.redirect('/');
    // التحقق من الصلاحية (عبر الرابط أو يدوي)
    if (req.session.canChat || req.session.user.isAdmin) {
        res.render('index', { user: req.session.user });
    } else {
        res.render('blocked');
    }
});

// لوحة التحكم - توليد الرابط
app.get('/admin', async (req, res) => {
    if (!req.session.user || !req.session.user.isAdmin) return res.send("غير مسموح");
    res.render('admin', { inviteLink: req.session.lastLink || null });
});

app.post('/generate-link', async (req, res) => {
    const code = crypto.randomBytes(4).toString('hex');
    await Invite.create({ code });
    req.session.lastLink = `${req.get('host')}/join/${code}`;
    res.redirect('/admin');
});

app.get('/join/:code', async (req, res) => {
    const invite = await Invite.findOne({ code: req.params.code, used: false });
    if (invite) {
        invite.used = true; // الرابط صالح لشخص واحد
        await invite.save();
        req.session.canChat = true;
        res.redirect('/'); // يوجهه ليسجل اسمه ثم يدخل الشات
    } else {
        res.send("الرابط غير صالح");
    }
});

// رفع الصور في الدردشة
app.post('/upload', upload.single('image'), (req, res) => {
    res.json({ url: req.file.path });
});

io.on('connection', (socket) => {
    socket.on('message', (data) => io.emit('message', data));
});

server.listen(process.env.PORT || 3000);
