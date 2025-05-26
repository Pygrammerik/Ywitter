# Ywitter

A simple Twitter-like social media platform built with Flask.

## Features

- User authentication (register, login, logout)
- Create, read, update, and delete tweets
- Like and retweet functionality
- User profiles with avatars
- Follow/unfollow users
- Image upload support
- Responsive design

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Pygrammerik/Ywitter.git
cd ywitter
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Initialize the database:
```bash
python main.py
```

5. Run the application:
```bash
python main.py
```

The application will be available at `http://localhost:5000`

## Project Structure

```
ywitter/
├── main.py              # Main application file
├── requirements.txt     # Project dependencies
├── static/             # Static files (CSS, JS, images)
│   ├── avatars/       # User avatars
│   └── media/         # Uploaded media files
└── templates/          # HTML templates
    ├── base.html      # Base template
    ├── index.html     # Home page
    ├── login.html     # Login page
    ├── register.html  # Registration page
    ├── profile.html   # User profile page
    └── landing.html   # Landing page
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
