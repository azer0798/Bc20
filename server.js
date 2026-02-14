const express = require('express');
const http = require('http');
const mongoose = require('mongoose');
const { Server } = require('socket.io');
const session = require('express-session');
const crypto = require('crypto');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// إعدادات الجلسة والقوالب
app.set('view engine', 'ejs');
app.set('views', __dirname);
app.use(express.urlencoded({ extended: true }));
app.use(session({ 
    secret: process.env.SESSION_SECRET || 'safe-key-123', 
    resave: false, 
    saveUninitialized: true 
}));

// الاتصال بـ MongoDB
mongoose.connect(process.env.MONGODB_URL)
    .then(() => console.log("DB Connected"))
    .catch(err => console.log("DB Error:", err));

// النماذج
const User = mongoose.model('User', { 
    username: String, 
    isAdmin: { type: Boolean, default: false },
    isApproved: { type: Boolean, default: false }
});

const Invite = mongoose.model('Invite', { 
    code: String, 
    used: { type: Boolean, default: false } 
});

// المسارات
app.get('/', (req, res) => res.render('login'));

app.post('/login', async (req, res) => {
    const { username } = req.body;
    let user = await User.findOne({ username });
    
    if (!user) {
        // أول شخص يسجل سيكون هو المدير (الأدمن) تلقائياً
        const count = await User.countDocuments({});
        user = await User.create({ 
            username, 
            isAdmin: count === 0, 
            isApproved: true 
        });
    }
    
    req.session.user = user;
    res.redirect('/chat');
});

app.get('/chat', async (req, res) => {
    if (!req.session.user) return res.redirect('/');
    
    // السماح إذا كان أدمن أو دخل عبر رابط دعوة صحيح
    if (req.session.user.isAdmin || req.session.canChat) {
        res.render('index', { user: req.session.user });
    } else {
        res.render('blocked');
    }
});

// لوحة التحكم
app.get('/admin', async (req, res) => {
    if (!req.session.user || !req.session.user.isAdmin) return res.send("غير مسموح لك بالدخول هنا.");
    res.render('admin', { inviteLink: req.session.lastLink || null });
});

app.post('/generate-link', async (req, res) => {
    if (!req.session.user || !req.session.user.isAdmin) return res.status(403).send("Forbidden");

    const code = crypto.randomBytes(4).toString('hex');
    await Invite.create({ code });

    // إنشاء الرابط ليعمل على راندر بشكل ديناميكي
    const fullLink = `${req.protocol}://${req.get('host')}/join/${code}`;
    req.session.lastLink = fullLink;
    res.redirect('/admin');
});

// الدخول عبر الرابط
app.get('/join/:code', async (req, res) => {
    const invite = await Invite.findOne({ code: req.params.code, used: false });
    if (invite) {
        invite.used = true; // الرابط صالح لمرة واحدة فقط
        await invite.save();
        req.session.canChat = true;
        res.redirect('/');
    } else {
        res.status(400).send("الرابط غير صالح أو تم استخدامه مسبقاً.");
    }
});

// Socket.io
io.on('connection', (socket) => {
    socket.on('message', (data) => io.emit('message', data));
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`Server on ${PORT}`));
