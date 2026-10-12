CXX ?= g++
CXXFLAGS ?= -O3 -march=native -std=c++17 -Wall -Wextra

incumbent-injector: injector.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f incumbent-injector
