/**
 * Paws & Claws Pet Grooming - Main JavaScript
 * Handles form validation, mobile navigation, and scroll effects
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const navbar = document.querySelector('.navbar');
  const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
  const navLinks = document.querySelector('.nav-links');
  const contactForm = document.querySelector('.contact-form');
  
  // Navigation Toggle
  if (mobileMenuBtn && navLinks) {
    mobileMenuBtn.addEventListener('click', () => {
      navLinks.classList.toggle('active');
      mobileMenuBtn.classList.toggle('active');
    });
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', (e) => {
      if (!mobileMenuBtn.contains(e.target) && !navLinks.contains(e.target)) {
        navLinks.classList.remove('active');
        mobileMenuBtn.classList.remove('active');
      }
    });
  }
  
  // Navbar scroll effect
  window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });
  
  // Smooth scroll for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
        
        // Close mobile menu if open
        if (navLinks && navLinks.classList.contains('active')) {
          navLinks.classList.remove('active');
          mobileMenuBtn.classList.remove('active');
        }
      }
    });
  });
  
  // Form Validation
  if (contactForm) {
    const nameInput = contactForm.querySelector('#name');
    const emailInput = contactForm.querySelector('#email');
    const phoneInput = contactForm.querySelector('#phone');
    const serviceSelect = contactForm.querySelector('#service');
    const messageInput = contactForm.querySelector('#message');
    
    // Email validation regex
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    
    // Phone validation regex (US format: (123) 456-7890, 123-456-7890, 123.456.7890, 1234567890)
    const phoneRegex = /^(\(\d{3}\)\s?|\d{3}[-.\s]?)\d{3}[-.\s]?\d{4}$/;
    
    // Name validation: at least 2 characters, letters and spaces only
    const nameRegex = /^[a-zA-Z\s]{2,}$/;
    
    // Message validation: at least 10 characters
    const messageRegex = /.{10,}/;
    
    // Validation functions
    const validateName = () => {
      const value = nameInput.value.trim();
      if (value.length === 0) {
        return { valid: false, error: 'Name is required' };
      }
      if (!nameRegex.test(value)) {
        return { valid: false, error: 'Please enter a valid name (letters and spaces only, minimum 2 characters)' };
      }
      return { valid: true };
    };
    
    const validateEmail = () => {
      const value = emailInput.value.trim();
      if (value.length === 0) {
        return { valid: false, error: 'Email is required' };
      }
      if (!emailRegex.test(value)) {
        return { valid: false, error: 'Please enter a valid email address' };
      }
      return { valid: true };
    };
    
    const validatePhone = () => {
      const value = phoneInput.value.trim();
      if (value.length === 0) {
        return { valid: true }; // Phone is optional
      }
      if (!phoneRegex.test(value)) {
        return { valid: false, error: 'Please enter a valid phone number' };
      }
      return { valid: true };
    };
    
    const validateService = () => {
      if (serviceSelect.value === '') {
        return { valid: false, error: 'Please select a service' };
      }
      return { valid: true };
    };
    
    const validateMessage = () => {
      const value = messageInput.value.trim();
      if (value.length === 0) {
        return { valid: false, error: 'Message is required' };
      }
      if (!messageRegex.test(value)) {
        return { valid: false, error: 'Message must be at least 10 characters' };
      }
      return { valid: true };
    };
    
    // Real-time validation
    const validateField = (field, validator) => {
      const result = validator();
      const formGroup = field.closest('.form-group');
      
      if (result.valid) {
        formGroup.classList.remove('error');
        formGroup.classList.add('success');
        field.setCustomValidity('');
      } else {
        formGroup.classList.remove('success');
        formGroup.classList.add('error');
        field.setCustomValidity(result.error);
      }
      
      return result.valid;
    };
    
    // Add event listeners for real-time validation
    nameInput.addEventListener('blur', () => validateField(nameInput, validateName));
    nameInput.addEventListener('input', () => {
      if (nameInput.value.length > 0) {
        validateField(nameInput, validateName);
      } else {
        nameInput.closest('.form-group').classList.remove('error', 'success');
        nameInput.setCustomValidity('');
      }
    });
    
    emailInput.addEventListener('blur', () => validateField(emailInput, validateEmail));
    emailInput.addEventListener('input', () => {
      if (emailInput.value.length > 0) {
        validateField(emailInput, validateEmail);
      } else {
        emailInput.closest('.form-group').classList.remove('error', 'success');
        emailInput.setCustomValidity('');
      }
    });
    
    phoneInput.addEventListener('blur', () => validateField(phoneInput, validatePhone));
    phoneInput.addEventListener('input', () => {
      if (phoneInput.value.length > 0) {
        validateField(phoneInput, validatePhone);
      } else {
        phoneInput.closest('.form-group').classList.remove('error', 'success');
        phoneInput.setCustomValidity('');
      }
    });
    
    serviceSelect.addEventListener('change', () => validateField(serviceSelect, validateService));
    
    messageInput.addEventListener('blur', () => validateField(messageInput, validateMessage));
    messageInput.addEventListener('input', () => {
      if (messageInput.value.length > 0) {
        validateField(messageInput, validateMessage);
      } else {
        messageInput.closest('.form-group').classList.remove('error', 'success');
        messageInput.setCustomValidity('');
      }
    });
    
    // Form submission
    contactForm.addEventListener('submit', (e) => {
      e.preventDefault();
      
      // Validate all fields
      const isNameValid = validateField(nameInput, validateName);
      const isEmailValid = validateField(emailInput, validateEmail);
      const isPhoneValid = validateField(phoneInput, validatePhone);
      const isServiceValid = validateField(serviceSelect, validateService);
      const isMessageValid = validateField(messageInput, validateMessage);
      
      // Check if all fields are valid
      if (isNameValid && isEmailValid && isPhoneValid && isServiceValid && isMessageValid) {
        // Simulate form submission
        const submitButton = contactForm.querySelector('.form-submit');
        const originalText = submitButton.textContent;
        
        submitButton.textContent = 'Sending...';
        submitButton.disabled = true;
        
        // Simulate API call
        setTimeout(() => {
          // Reset form
          contactForm.reset();
          
          // Remove validation classes
          contactForm.querySelectorAll('.form-group').forEach(group => {
            group.classList.remove('error', 'success');
          });
          
          // Show success message
          submitButton.textContent = 'Message Sent!';
          
          // Reset button after delay
          setTimeout(() => {
            submitButton.textContent = originalText;
            submitButton.disabled = false;
          }, 3000);
        }, 1500);
      } else {
        // Scroll to first error
        const firstError = contactForm.querySelector('.form-group.error');
        if (firstError) {
          firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    });
  }
  
  // Intersection Observer for scroll animations
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('fade-in');
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);
  
  // Observe elements for animation
  document.querySelectorAll('.service-card, .about-content, .contact-container').forEach(el => {
    observer.observe(el);
  });
  
  // Scroll reveal for specific elements
  const revealElements = () => {
    const elements = document.querySelectorAll('.service-card');
    elements.forEach((el, index) => {
      if (index % 2 === 0) {
        el.classList.add('slide-in-left');
      } else {
        el.classList.add('slide-in-right');
      }
    });
  };
  
  // Trigger reveal on scroll
  window.addEventListener('scroll', revealElements);
  revealElements(); // Initial check
});
