-- Create the 'users' table
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(255) NOT NULL UNIQUE,
    `password_hash` VARCHAR(255) NOT NULL
);

-- Create the 'chats' table
CREATE TABLE IF NOT EXISTS `chats` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `prompt` TEXT NOT NULL,
    `answer` TEXT NOT NULL,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`)
);
