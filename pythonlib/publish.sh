rm -rf ./dist
rm -rf ./camoufox/*.mmdb
rm -rf ./camoufox/*.png

python -m build
twine check dist/*

read -p "Confirm publish? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    twine upload dist/*
fi
